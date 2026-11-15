# Runbook: reconciliation mismatch

**What it is.** Two watchdogs compare records that must agree.
- **Paper:** `scripts/paper_reconcile.py` (every minute in market hours and once after the close). It closes the positions of any account whose kill switch is FLATTEN, then compares the OMS log with the paper orders, and the orders' fills with what the paper book recorded (`paper/oms.reconcile`, `position_mismatches`). A mismatch **pauses the strategy and saves that pause** (a halt, not a note) and the job exits 1, so the runner alerts. A closing order that could not be sent also exits 1 and is retried next minute.
- **Live (when live exists):** `execution/live_reconcile.reconcile_live` compares the OMS's fills with the real Kite holdings (settled plus unsettled). The broker is the truth, but it also holds what the owner bought by hand: **more** at the broker than we bought is expected, **less** is a mismatch. An unreadable broker account is itself a mismatch (`BROKER_UNREACHABLE`) and halts trading. Cash is not compared; a stock with no Kite symbol is ignored.

**The alert.** The job's output lists each mismatch (`kind`, the client order id if any, and the detail).

**Do this.**
1. Do not resume. Read the mismatch lines: `uv run python scripts/paper_reconcile.py` (safe to re-run; it also retries closing orders for FLATTEN accounts).
2. Decide which side is wrong. For an order mismatch compare the OMS event log with `paper_order` for the client order id; for a position mismatch compare the OMS positions with the paper book. For live, compare with the broker's order book and holdings in the Kite console. A fill the broker has and we do not is the dangerous case (an unknown position): leave the switch paused until it is understood.
3. Fix the cause, not the number: a late fill, a duplicate event or a manual trade is a data problem to correct with an audited entry or a resolved order; never edit the log. If the OMS crashed between sending an order and recording it, `Oms.recover()` resolves it by the client order id tag at the next start (an order sent but not recorded is looked up at the broker, not resent).
4. Re-run the reconciler until it reports `0 mismatch(es)`.
5. Resume explicitly: `uv run python scripts/kill_switch.py resume --strategy ID --by WHO --reason TEXT` (see `kill-switch.md`), then `scripts/platform_boot.py` (use `--operator` only if the platform was HALTED and you have understood why).

**Evidence that each path is exercised:** `tests/integration/paper/test_oms.py` (a mismatch pauses the strategy and the pause is saved), `tests/fault/test_scenarios.py` (a crash between send and record; a reconcile that does not report a false mismatch), `tests/unit/execution` for the live comparison. **Drill record:** `docs/drills/2026-11-15-drills.md`.
