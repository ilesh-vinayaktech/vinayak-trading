# Runbook: stop Kite and switch the daily prices to NSE bhavcopy (the cutoff)

One-time and not reversible in spirit: after it, Kite's stored history never changes again and every
later corporate action is applied by us. Take it slowly; nothing here needs to be done in a hurry.

## What the switch does
`ALGO_PRICE_SOURCE=bhavcopy` + `ALGO_PRICE_CUTOFF=YYYY-MM-DD` makes the reader serve **Kite's bars up to
and including the cutoff day, NSE bhavcopy after it** (`BarReader`, `algo.data.price_source`).
- Kite bars are vendor-adjusted. For each of them our factors are skipped for every non-dividend action
  with an ex-date on or before the bar's `adjusted_through` day; a dividend is skipped only when the
  Kite/NSE step across its ex-date shows Kite took it out (`vendor_applied_dividends`).
- NSE bars after the cutoff are raw: every action with a later ex-date is applied by us.
- The study runner does NOT follow the cutoff (it reads the frozen Kite history on purpose).

## Before the day
1. Everything the cutoff relies on is in the database: Kite bars through the cutoff day, final (not the
   evening's provisional candles), and the NSE bhavcopy for the same days.
2. The daily jobs for the NSE side are healthy for a week: bhavcopy load, corporate-actions window
   (`corporate-actions-daily`), gap refill. After the cutoff nothing else supplies prices.
3. No open review item that could touch a stock you trade (the queue should be empty or understood).

## On the day (pick a cutoff day D with both files final: the day after is best)
1. **Re-download the last days from Kite** (the evening candle of a day is provisional): delete only the
   rows of the last 2 trading days that are NOT frozen, then `scripts/kite_load_days.py --from <d-1> --to D`.
   Frozen rows cannot be deleted (migration 058); if you must, see "Fixing frozen history" below.
2. **Seam check:** `reader.seam_mismatches(conn, D)` (or the SQL in the TODO) must list only stocks that
   have an action with an ex-date after D that Kite already adjusted. Anything else: stop and look.
3. **Freeze:** `scripts/freeze_kite.py take --through D --note "..."` then `... verify` (clean).
4. **Stop Kite:** the daily-candle load and the feed. Keep the raw archive (`data/lake`) and the Kite bars.
5. **Set the two values** in `.env`: `ALGO_PRICE_SOURCE=bhavcopy`, `ALGO_PRICE_CUTOFF=D`. Restart API,
   worker and paper runner (`./start_all.sh rebuild`).
6. **Check on screen:** one stock with a recent dividend and one with a recent demerger on the chart in
   Data Explorer: no jump at D, prices after D are NSE's.

## After the cutoff (daily)
- Splits and bonuses apply by themselves. **Rights, demergers, buy-backs and any action the parser could
  not price land in the review queue** (the Action worklist page): a person decides them before the
  ex-date. The daily window job lists announced actions about 10 days ahead.
- The paper page warns about announced actions on positions and orders.

## Undo
Set `ALGO_PRICE_SOURCE=kite`, remove `ALGO_PRICE_CUTOFF`, restart. Kite's history stays valid through D;
bars after D only exist if Kite was loaded again (re-run `kite_load_days.py`).

## Fixing frozen history (rare, deliberate)
The guard refuses both inserts and deletes inside a freeze. A deliberate fix runs in its own
transaction with `SET LOCAL algo.allow_frozen_write = 'on'`, then **take a new freeze** (append-only)
and point anything that recorded the old one at it. Record why in the freeze note.
Lesson (2026-11-14): deleting "the last 2 days" removed frozen rows because the delete was not guarded.
