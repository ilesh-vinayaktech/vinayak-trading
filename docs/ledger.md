# Financial ledger (`src/algo/ledger/ledger.py`)

The single source of truth for cash, positions, fees and P&L. The backtest engine keeps no balances
of its own: it posts events to the ledger and reads everything back from it.

* **Append-only, numbered entries**, each citing its source event (`ref`): `trade:<n>` or
  `action:<instrument>:<ex_date>:<kind>:<n>`. A source event can be booked once (`DuplicateBooking`).
* **Triple entry per trade.** BUY = position(+qty, +cost) + cash(-value) [+ fee + cash(-fee)].
  SELL = position(-qty, -cost removed) + cash(+proceeds) + realized P&L(proceeds - cost removed)
  [+ fee + cash(-fee)]. Average-cost accounting; a full exit clears the basis exactly.
* **Corporate actions:** bonus/split changes share count, not cost (average cost falls); dividends
  credit cash on the shares held. Actions the accounting cannot value (demerger child shares,
  rights) are written as `event / UNMODELLED:<kind>` entries, never dropped.
* **`reconcile()`** re-derives every balance from the entries alone and returns the problems:
  running state vs entries, per-trade cross-checks (cash = cost, realized = proceeds - cost removed,
  fee = cash paid), duplicate or renumbered entries, negative positions, orphan cost basis, and the
  identity `(cash - initial) + cost basis - realized - dividends + fees = 0`. With prices it also
  checks `equity - initial = net P&L`. Tolerance 1e-9 rupees (average-cost division is 28-digit).
* **Persistence:** `backtest_ledger` (every entry) and the view `backtest_ledger_pnl` are the only
  sanctioned source for reported P&L. `backtest_run.ledger_reconciled` must be true for a run to
  support promotion.

## Security conversion (ISIN change)

A conversion is a corporate-action INSTRUCTION, never an inference. `SAME_ISSUER_ISIN_CHANGE` says two ISINs belong to one issuer; it does not say how a holding converts
(1:1 rename, a split, something else). The ledger converts only what a VERIFIED `Conversion` says, with its own ratio, effective date and evidence. Without one, a held source
position is flagged `UNMODELLED:ISIN_CHANGE`, like a demerger the accounting cannot value. Implemented by `Ledger.register_conversion` / `apply_conversion`.

| Attribute | Treatment |
|---|---|
| Quantity | target = source x `num` / `den` (target shares per `den` source shares) |
| Total cost basis | moved exactly; nothing created or lost; average cost falls by the ratio |
| Realised P&L, cash, fees | none: a conversion is not a sale and a repurchase |
| Unrealised P&L | recomputed from the target's price; moves only with the market |
| Historical trades, fees, booked dividends | never rewritten; the old instrument keeps its own entries |

Example: 100 old shares, cost 25,000 (average 250), ratio 10:1 -> 1,000 new shares, cost 25,000 (average 25), realised P&L 0.

**Instruction:** `source`, `target`, `effective` (first day the target holds the position), optional `last_source_session`, `num`, `den`, `ref` (the source event and the idempotency
key, e.g. `convert:2653:1589:2024-01-05`), `verified` (must be true), `evidence` (at least one reference), `absorbs` (the corporate action it replaces, e.g. the same-date split, so one
economic event is never applied twice). **Entries** (append-only, both under `ref`): `position/CONVERT_OUT` (source, minus the whole quantity, minus the whole cost) and
`position/CONVERT_IN` (target, quantity x ratio, plus the same cost). No cash, fee or P&L entry.

**Order of a day:** source trades through the day before `effective`; then, on the first session on or after `effective` and before that day's actions and orders, `apply_conversion`;
the target's `absorbs` action is skipped; from `effective` the target is tradable and the source is not.

**Invariants** (a breach raises or is returned by `reconcile()`): quantity x den = source x num; cost out = cost in; no P&L, cash or fee on a conversion; one conversion per source and per
target and one booking per `ref`; no source trade on or after `effective`, no target trade before it; no residual source position; rebuilding from entries alone gives identical balances;
an unverified or evidence-free instruction is refused at registration. Not in scope: the membership handover, which this is a prerequisite for.

**Where the instruction lives and how the engine uses it:** table `security_conversion` (migration 025; only `VERIFIED` rows are loaded by `algo.data.conversions.load_conversions`), recorded
from a reviewed config in `config/security_conversions/` by `scripts/record_security_conversion.py` (dry run by default; `--apply` commits). `run_backtest` registers a verified instruction when its
target is in the run, converts a held source on the first session of the target (before that day's actions and orders) and skips the absorbed corporate action. A held source whose
ISIN-change link has no usable instruction, or whose target is outside the run, is flagged `UNMODELLED:ISIN_CHANGE` (the run is then not `accounting_complete`). `RunResult.conversions` lists
what was applied; the entries themselves are persisted in `backtest_ledger` like any other. Checked on the real NESTLEIND prices by `scripts/verify_nestleind_conversion.py` (read-only, in-memory position).

Not built yet: broker-reported vs internal ledger and their reconciliation diff (live), margin
ledger, fee types beyond a single commission (the versioned cost schedule adds brokerage, STT,
exchange charges, GST, SEBI fee, stamp duty), slippage cost reporting.
