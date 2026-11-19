"use client";

import type { MarketContext } from "@/lib/schemas";

const Glyph = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
const price = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const BREAKOUT = { "crossed today": "the latest close crossed above the previous 20-day high (the close before it was not above)", "already above": "the latest close is above the previous 20-day high, as the close before it also was", none: "no close above the previous 20-day high" } as const;
const REGIME = { uptrend: "Uptrend", downtrend: "Downtrend", sideways: "Sideways" } as const;

function Row({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-2 rounded border border-line bg-slate-50 p-2 text-sm" aria-label={title}>
      <div className="font-semibold">{title}</div>
      <div className="mt-0.5 text-xs text-slate-700">{children}</div>
    </div>
  );
}

/** What the study did and did not establish, stated on the screen next to the numbers (scripts/study_conditions.py, 2026-11-19). */
const CONFIDENCE =
  "Research confidence: low for direction. 232 tests (conditions across horizons and market regimes) were run on about 2,600 NSE stocks in 2019 to 2023, with case counts from a few thousand to several hundred thousand; none survived correction for the number of tests, so nothing here predicts a rise or a fall. The one steady pattern: momentum measures did slightly better while Nifty was in an uptrend and weak or oversold stocks did worse while it was falling (a few tenths of a percent over 10 sessions, not significant after correction).";

function Body({ data, loading, failed }: { data: MarketContext | undefined; loading: boolean; failed: boolean }) {
  if (loading) return <p className="mt-2 text-xs text-slate-500" role="status">Loading the market context…</p>;
  if (failed || !data) return <p className="mt-2 text-xs text-slate-600">The market context could not be loaded.</p>;
  const { regime, sector, strength, momentum, breakout: b } = data;
  return (
    <>
      <Row title="Market regime">
        {regime ? (
          <>
            Nifty 50: <span className="font-semibold">{REGIME[regime.label]}</span> (close {regime.nifty_close.toLocaleString("en-IN")} on {regime.as_of}). A description of the index trend, not a recommendation.
          </>
        ) : (
          "Not enough Nifty history to say."
        )}
      </Row>
      <Row title="Sector strength">
        {sector ? (
          <>
            {sector.name} is <span className="font-semibold">{sector.verdict}</span> the market over {sector.window} sessions: median {pct(sector.sector_ret)} against {pct(sector.market_ret)} for all stocks ({sector.n} stocks in the sector).
          </>
        ) : (
          "This stock has no sector on file, or there is too little history."
        )}
      </Row>
      <Row title="Relative strength">
        {strength ? (
          <>
            Over 60 sessions the stock moved {pct(strength.ret_60d)}; Nifty 50 {pct(strength.nifty_ret_60d)}; its sector (median) {pct(strength.sector_ret_60d)}.
          </>
        ) : data.adjusted ? (
          "Withheld: a split or bonus in the last 70 sessions makes the stock's own prices not comparable."
        ) : (
          "Not enough history."
        )}
      </Row>
      <Row title="Momentum and trend">
        {momentum ? (
          <>
            RSI {momentum.rsi === null ? "n/a" : momentum.rsi.toFixed(0)}; ADX {momentum.adx === null ? "n/a" : momentum.adx.toFixed(0)}
            {momentum.adx_label ? ` (${momentum.adx_label}: how steady the move is, whichever way it points)` : ""}; 20-day average {momentum.ema_trend ?? "n/a"} the 50-day.
          </>
        ) : data.adjusted ? (
          "Withheld: a split or bonus in the last 70 sessions."
        ) : (
          "Not enough history."
        )}
      </Row>
      <Row title="Breakout and extension context">
        {b ? (
          <ul className="list-disc space-y-0.5 pl-4">
            <li>20-day high: {b.above_20d_high === null ? "not enough history" : `the latest close is ${b.above_20d_high ? "above" : "not above"} the previous 20-day high${b.high_20d === null ? "" : ` (${price(b.high_20d)})`}`}.</li>
            <li>52-week high: {b.new_52w_high === null ? "not enough history" : `${b.new_52w_high ? "a new 52-week high" : "not a new 52-week high"}${b.high_52w === null ? "" : ` (previous high ${price(b.high_52w)})`}`}.</li>
            <li>Distance from the 20-day average (EMA20): {b.extension_atr === null ? "not available" : `${Math.abs(b.extension_atr).toFixed(1)} ATR ${b.extension_atr >= 0 ? "above" : "below"} it`}.</li>
            <li>Breakout status: {b.breakout === null ? "not enough history" : BREAKOUT[b.breakout]}.</li>
            <li className="list-none text-slate-500">Facts about the latest completed daily candle. They do not say what the stock will do next.</li>
          </ul>
        ) : data.adjusted ? (
          "Withheld: a split or bonus in the last 70 sessions."
        ) : (
          "Not enough history."
        )}
      </Row>
    </>
  );
}

/** The rail button for the market context: where the stock stands today (Nifty regime, sector, relative strength, momentum), described and never predicted, with the research's limits beside it. */
export function MarketContextButton({ on, onToggle, open, onOpen, data, loading, failed }: { on: boolean; onToggle: () => void; open: boolean; onOpen: (v: boolean) => void; data: MarketContext | undefined; loading: boolean; failed: boolean }) {
  return (
    <div className="relative">
      <button
        type="button"
        title="Market context: the Nifty trend, the stock's sector and relative strength, RSI and ADX. A description, not a signal"
        aria-label="Market context"
        aria-pressed={on}
        onClick={onToggle}
        className={`relative flex h-9 w-9 items-center justify-center rounded-md transition-colors ${on ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}
      >
        <Glyph />
      </button>
      {on && open ? (
        <div role="group" aria-label="Market context details" className="absolute bottom-0 left-full z-30 ml-2 max-h-[min(32rem,75vh)] w-80 overflow-y-auto rounded-lg border border-line bg-white p-3 text-left shadow-lg">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-sm font-semibold">
              Market context{data?.as_of ? <span className="text-xs font-normal text-slate-500"> (as of {data.as_of})</span> : null}
            </span>
            <button type="button" aria-label="Close the market context" onClick={() => onOpen(false)} className="rounded px-1.5 text-slate-500 hover:bg-slate-100">×</button>
          </div>
          <p className="rounded bg-amber-50 p-2 text-xs text-amber-900">This describes where the stock stands. It is not a buy or sell signal and not a prediction of direction.</p>
          <Body data={data} loading={loading} failed={failed} />
          <p className="mt-3 rounded bg-slate-100 p-2 text-xs text-slate-700" aria-label="Research confidence">{CONFIDENCE}</p>
        </div>
      ) : null}
      {on && !open ? (
        <button type="button" aria-label="Show the market context" title="Show the market context" onClick={() => onOpen(true)} className="absolute -right-1 top-1/2 flex h-5 w-3 -translate-y-1/2 items-center justify-center rounded-r bg-slate-200 text-[10px] text-slate-700">
          ›
        </button>
      ) : null}
    </div>
  );
}
