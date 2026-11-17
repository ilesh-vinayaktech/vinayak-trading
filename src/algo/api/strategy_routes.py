# ruff: noqa: E501
"""Strategies: the signed-in user's saved, named strategy settings (index, number of stocks, time frame, rules).

Every route acts on the caller's own strategies (no user id in any path); an id that is not theirs looks like it does not
exist. The paper account picks one (`use`) and follows later edits of it. UNVALIDATED research: nothing here can place a
real order."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api import queries
from algo.api.paper_routes import _options, _params, _st
from algo.api.security import CurrentUser, WConn
from algo.data.reader import IST
from algo.factory import registry, signal_cache
from algo.factory import signals as def_signals
from algo.factory import study as fstudy
from algo.paper import configs
from algo.portal import audit
from algo.research import fundamentals_book, holdout_lock, study_jobs
from algo.research.holdout_lock import HoldoutError
from algo.research.study import Segment, StudyError
from algo.strategies import screener_signals
from algo.strategies.screener import ScreenSpec
from algo.strategies.signals import replay
from algo.strategies.trend_pullback import LOOKBACK_DAYS, TrendPullbackParams
from algo.strategy import stage

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class ScreenBody(ScreenSpec):
    """The rules of a screener strategy plus the market-cap classes it picks from."""

    segments: list[Segment] = Field(min_length=1)


class StrategyBody(BaseModel):
    name: str = Field(max_length=60)
    universe: str = Field(max_length=20)
    max_instruments: int | None = Field(default=None, ge=5, le=500)
    timeframe: str = Field(max_length=5)
    params: dict[str, int] = Field(default_factory=dict)
    screen: ScreenBody | None = (
        None  # given: a screener strategy (universe, cap and time frame are then fixed)
    )


SCREENER_SLOTS = (5, 10, 20)


def _settings(body: StrategyBody) -> dict[str, Any]:
    """What `configs.create/update` take for this body: a trend strategy's validated params, or a screener's rules."""
    if body.screen is None:
        if body.universe == configs.SEGMENTS:
            raise HTTPException(400, "unknown universe 'segments'")
        return {
            "universe": body.universe,
            "max_instruments": body.max_instruments,
            "params": _params(body.params),
        }
    spec = ScreenSpec.model_validate(body.screen.model_dump(exclude={"segments"}))
    if (why := spec.problem()) is not None:
        raise HTTPException(400, why)
    slots = body.params.get("max_positions", 10)
    if slots not in SCREENER_SLOTS:
        raise HTTPException(400, f"max_positions must be one of {list(SCREENER_SLOTS)}")
    return {
        "universe": configs.SEGMENTS, "max_instruments": None, "params": {"max_positions": slots},
        "screen": {"screen": spec.model_dump(mode="json"), "segments": list(body.screen.segments)},
        "strategy_id": "screener",
    }  # fmt: skip


def _shown(c: dict[str, Any], current_stage: str = "RESEARCH") -> dict[str, Any]:
    return {
        **c, "config_id": str(c["config_id"]), "created_at": c["created_at"].isoformat(),
        "stage": current_stage,
    }  # fmt: skip


def _fail(e: configs.ConfigError) -> HTTPException:
    return HTTPException(404 if "no such" in str(e) else 400, str(e))


@router.get("")
def list_strategies(who: CurrentUser, conn: WConn) -> dict[str, Any]:
    return {
        "label": "UNVALIDATED",
        "options": _options(),
        "strategies": [
            _shown(c, stage.current(conn, c["config_id"]))
            for c in configs.list_for(conn, who.session.user_id)
        ],
    }


def _change(
    request: Request,
    who: CurrentUser,
    conn: WConn,
    action: str,
    config_id: UUID,
    detail: dict[str, Any],
) -> None:
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action=f"strategy.{action}",
        actor_user_id=who.session.user_id,
        target_type="strategy_config",
        target_id=str(config_id),
        detail=detail,
    )


@router.post("")
def create(body: StrategyBody, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    mine = _settings(body)
    try:
        config_id = configs.create(
            conn, who.session.user_id, name=body.name, timeframe=body.timeframe,
            now=_st(request).clock.now(), **mine,
        )  # fmt: skip
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(
        request,
        who,
        conn,
        "created",
        config_id,
        {"name": body.name.strip(), "universe": mine["universe"]},
    )
    return {"config_id": str(config_id)}


class DefinitionRun(BaseModel):
    family_id: int = 1  # the research family its tries count in
    chain: bool = True  # carry on by itself: judge the trials, then run the inner holdout if the verdict passed


@router.post("/definitions/{strategy_id}/{version}/study")
def run_definition_study(
    strategy_id: str,
    version: int,
    request: Request,
    who: CurrentUser,
    conn: WConn,
    body: DefinitionRun | None = None,
) -> dict[str, int]:
    """Backtest a generated strategy definition: its standard study (2016 to 2022 research window, a counted grid of its own numbers) is registered once and its trials queued. The result
    page then shows every trial with its equity curve, trades and the validation verdict."""
    now = _st(request).clock.now()
    try:
        eid, run = fstudy.start(
            conn,
            who.session.user_id,
            strategy_id,
            version,
            now,
            family_id=(body or DefinitionRun()).family_id,
            chain=(body or DefinitionRun()).chain,
        )
    except registry.RegistryError as e:
        raise HTTPException(404, str(e)) from e
    except (StudyError, study_jobs.JobError) as e:
        raise HTTPException(400, str(e)) from e
    except HoldoutError as e:
        raise HTTPException(409, f"research is locked: {e}") from e
    audit.record(
        conn, now=now, action="study.registered", actor_user_id=who.session.user_id, target_type="experiment",
        target_id=str(eid), detail={"strategy_id": strategy_id, "version": version, "run_id": run},
    )  # fmt: skip
    return {"experiment_id": eid, "run_id": run}


def _research_end(conn: Any, end: date) -> date:
    """Strategy decisions after the research window (2024-12-31) are never served to research-facing routes, for any strategy (docs/holdout-policy-v3.md section 6):
    seeing how a strategy behaved on the holdout dates would teach the next candidate. Fails closed when the lock is not anchored."""
    try:
        return min(end, holdout_lock.require(conn).development_end)
    except HoldoutError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/definitions/{strategy_id}/{version}/signals")
def definition_signals(
    strategy_id: str,
    version: int,
    instrument_id: int,
    start: date,
    end: date,
    request: Request,
    who: CurrentUser,
    conn: WConn,
) -> dict[str, Any]:
    """One stock's buy/sell decisions under a generated definition over the asked range, to the latest bar. The decisions are kept in definition_signal_series / _day: a later request inside
    the kept range is served from it, one that reaches past it computes only the new days, and one that starts earlier recomputes the whole range."""
    try:
        defn = registry.get(conn, strategy_id, version)
    except registry.RegistryError as e:
        raise HTTPException(404, str(e)) from e
    if end < start:
        raise HTTPException(422, "end before start")
    if (end - start).days > MAX_DEFINITION_SIGNAL_DAYS:
        raise HTTPException(422, "range longer than 11 years")
    if queries.instrument(conn, instrument_id) is None:
        raise HTTPException(404, f"no instrument {instrument_id}")
    end = _research_end(conn, end)

    def bars_of(iid: int, lo: date, hi: date) -> list[Any]:
        return list(
            queries.reader_for(conn, iid)[0].issuer_history(iid, lo, hi, adjust="split").bars
        )

    def day_of(b: Any) -> date:
        d: date = b.ts.astimezone(IST).date()
        return d

    sha, now = defn.sha256, _st(request).clock.now()
    cached = signal_cache.get(conn, strategy_id, version, sha, instrument_id, start, end)
    continuing = cached is not None and start >= cached.first_day and cached.last is not None
    # continuing needs the sessions straight after the stored last day, even when the asked range starts later
    bars = [
        b
        for b in bars_of(
            instrument_id,
            min(start, cached.last_day + timedelta(days=1)) if continuing and cached else start,
            end,
        )
    ]
    try:
        if continuing and cached and cached.last is not None:
            new = [day_of(b) for b in bars if day_of(b) > cached.last_day]
            fresh = def_signals.compute(
                conn,
                defn,
                instrument_id,
                new,
                bars_of,
                held=cached.last.holding_after,
                after=cached.last_day,
            )
            signal_cache.save(
                conn, strategy_id, version, sha, instrument_id, fresh, now, replace=False
            )
            shown = [d for d in [*cached.days, *fresh] if start <= d.day <= end]
        else:
            allday = [day_of(b) for b in bars if start <= day_of(b) <= end]
            fresh = def_signals.compute(conn, defn, instrument_id, allday, bars_of)
            signal_cache.save(
                conn, strategy_id, version, sha, instrument_id, fresh, now, replace=True
            )
            shown = fresh
    except (def_signals.SignalsError, HoldoutError) as e:
        raise HTTPException(409, str(e)) from e
    by_day = {day_of(b): (i, b) for i, b in enumerate(bars)}
    days = []
    for g in shown:
        i, b = by_day[g.day]
        nxt = bars[i + 1] if g.action and i + 1 < len(bars) else None
        days.append(
            {
                "day": g.day.isoformat(), "close": _num(b.close), "sma": None, "rsi": None, "ready": g.ready, "action": g.action, "reason": g.reason,
                "holding_after": g.holding_after, "fill_day": day_of(nxt).isoformat() if nxt else None, "fill_price": _num(nxt.open) if nxt else None,
            }
        )  # fmt: skip
    return {
        "label": "UNVALIDATED", "strategy": f"{strategy_id} v{version}", "params": {}, "notes": def_signals.NOTES,
        "summary": {"buys": sum(g.action == "BUY" for g in shown), "sells": sum(g.action == "SELL" for g in shown)}, "days": days,
    }  # fmt: skip


@router.post("/{config_id}")
def change(
    config_id: UUID, body: StrategyBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    mine = _settings(body)
    params = mine["params"]
    mine.pop("strategy_id", None)  # a strategy's kind never changes
    try:
        configs.update(
            conn, who.session.user_id, config_id, name=body.name, timeframe=body.timeframe, **mine,
        )  # fmt: skip
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(
        request,
        who,
        conn,
        "changed",
        config_id,
        {"name": body.name.strip(), "universe": mine["universe"], "params": params},
    )
    return {"ok": True}


class StageBody(BaseModel):
    to_stage: str = Field(max_length=10)
    reason: str = Field(max_length=500)
    run_id: int | None = Field(default=None, ge=1)


def _own(conn: WConn, who: CurrentUser, config_id: UUID) -> None:
    if configs.get(conn, who.session.user_id, config_id) is None:
        raise HTTPException(404, "no such strategy")


@router.get("/{config_id}/stage")
def stage_history(config_id: UUID, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    _own(conn, who, config_id)
    return {
        "label": "UNVALIDATED",
        "stage": stage.current(conn, config_id),
        "history": [{**h, "at": h["at"].isoformat()} for h in stage.history(conn, config_id)],
    }


@router.post("/{config_id}/stage")
def move_stage(
    config_id: UUID, body: StageBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    _own(conn, who, config_id)
    try:
        stage.change(
            conn, config_id, body.to_stage, who.session.user_id, _st(request).clock.now(),
            reason=body.reason, run_id=body.run_id,
        )  # fmt: skip
    except stage.StageError as e:
        raise HTTPException(400, str(e)) from e
    _change(
        request, who, conn, "stage_changed", config_id, {"to": body.to_stage, "run_id": body.run_id}
    )
    return {"stage": body.to_stage}


@router.post("/{config_id}/use")
def use(
    config_id: UUID,
    request: Request,
    who: CurrentUser,
    conn: WConn,
    mode: Literal["paper", "live"] = "paper",
) -> dict[str, bool]:
    try:
        configs.use(conn, who.session.user_id, config_id, mode.upper())
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(request, who, conn, "used", config_id, {"mode": mode})
    return {"ok": True}


@router.post("/{config_id}/delete")
def delete(config_id: UUID, request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    try:
        configs.delete(conn, who.session.user_id, config_id)
    except configs.ConfigError as e:
        raise _fail(e) from e
    _change(request, who, conn, "deleted", config_id, {})
    return {"ok": True}


NOTES = [
    "Decisions only: this is not a backtest and shows no profit or loss.",
    "It reads one stock alone. It ignores the limit on how many stocks are held at once, the choice among stocks that are oversold on the same day, and index membership, so a BUY here is the strategy's signal for this stock, not a promise the whole strategy would have bought it.",
    "A decision is made after the day's close and filled at the next session's open.",
]
SCREENER_HISTORY_DAYS = (
    420  # calendar days of bars before the range: the 252-session one-year change
)
SCREENER_NOTES = [
    "Decisions only: this is not a backtest and shows no profit or loss.",
    "A screener strategy runs the screen after every session. A BUY here means the stock started matching the screen that day; a SELL means it stopped matching (it is then sold, and not bought back until it matches again).",
    "It reads this stock alone. It ignores the limit on how many stocks are held at once and the ranking among stocks that match on the same day, so a BUY here is the screen's signal for this stock, not a promise the whole strategy would have bought it.",
    "A stock needs a full year of history before a one-year condition can match. A decision is made after the day's close and filled at the next session's open.",
]
MAX_SIGNAL_DAYS = 366 * 10
MAX_DEFINITION_SIGNAL_DAYS = 366 * 11


@router.get("/{config_id}/signals")
def signals(
    config_id: UUID,
    instrument_id: int,
    start: date,
    end: date,
    request: Request,
    who: CurrentUser,
    conn: WConn,
    holding: bool = False,
) -> dict[str, Any]:
    """One stock's buy/sell decisions under this strategy from `start` to `end`; `holding` starts the replay already holding it."""
    mine = configs.get(conn, who.session.user_id, config_id)
    if mine is None:
        raise HTTPException(404, "no such strategy")
    if end < start:
        raise HTTPException(422, "end before start")
    if (end - start).days > MAX_SIGNAL_DAYS:
        raise HTTPException(422, "range longer than 10 years")
    if queries.instrument(conn, instrument_id) is None:
        raise HTTPException(404, f"no instrument {instrument_id}")
    end = _research_end(conn, end)
    if mine["screen"] is not None:
        history = queries.reader_for(conn, instrument_id)[0].issuer_history(
            instrument_id, start - timedelta(days=SCREENER_HISTORY_DAYS), end, adjust="split"
        )
        spec = ScreenSpec.model_validate(mine["screen"]["screen"])
        filings = (
            fundamentals_book.load(conn, [instrument_id], start, end)
            if spec.needs_fundamentals()
            else None
        )
        rows = screener_signals.replay(history.bars, start, end, spec, filings, instrument_id)
    else:
        params = TrendPullbackParams(**mine["params"])
        history = queries.reader_for(conn, instrument_id)[0].issuer_history(
            instrument_id, start - timedelta(days=LOOKBACK_DAYS), end, adjust="split"
        )
        rows = replay(history.bars, params, start, end, holding=holding)
    days = [
        {
            "day": r.day.isoformat(), "close": _num(r.close), "sma": _num(r.sma), "rsi": _num(r.rsi), "ready": r.ready,
            "action": r.action, "reason": r.reason, "holding_after": r.holding_after,
            "fill_day": r.fill_day.isoformat() if r.fill_day else None, "fill_price": _num(r.fill_price),
        }
        for r in rows
    ]  # fmt: skip
    return {
        "label": "UNVALIDATED",
        "strategy": mine["name"],
        "params": mine["params"],
        "notes": SCREENER_NOTES if mine["screen"] is not None else NOTES,
        "summary": {
            "buys": sum(r.action == "BUY" for r in rows),
            "sells": sum(r.action == "SELL" for r in rows),
        },
        "days": days,
    }


def _num(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")
