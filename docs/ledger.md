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

Not built yet: broker-reported vs internal ledger and their reconciliation diff (live), margin
ledger, fee types beyond a single commission (the versioned cost schedule adds brokerage, STT,
exchange charges, GST, SEBI fee, stamp duty), slippage cost reporting.
