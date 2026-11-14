from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from algo.sandbox.host import Limits, SandboxedStrategy
from algo.strategy.context import PortfolioView

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
QUICK = Limits(call_timeout_s=20.0)


def ctx(now=NOW, data=None, portfolio=None):
    return SimpleNamespace(
        now=lambda: now,
        mode="research",
        portfolio=portfolio or PortfolioView.of(D(1000), {}, D(1000)),
        data=data or SimpleNamespace(history=lambda ids, lookback, adjusted=True: {}),
    )


def sandbox(spec, params=None, **kw):
    kw.setdefault("limits", QUICK)
    return SandboxedStrategy(
        spec,
        params or {},
        import_roots=[
            ROOT
        ],  # so `tests.support...` imports; reading is allowed only under src and tests
        read_roots=[ROOT / "src", ROOT / "tests"],
        **kw,
    )


def adversarial(name, **kw):
    return sandbox(f"tests.support.adversarial:{name}", **kw)
