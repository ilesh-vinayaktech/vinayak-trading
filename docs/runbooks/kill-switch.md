# Runbook: the kill switch

**Modes.** PAUSE: no new orders. CANCEL: also fails approved paper orders that have not filled. FLATTEN: also asks for positions to be closed (needs `--emergency-override`; for paper it is recorded and blocks new orders, and `paper_reconcile.py` sends the closing orders). RUNNING is the normal state; **resume is always explicit**. Every change stores who and why. The switch can be global or per strategy (`--strategy ID`). It is also on the portal's Risk and kill switch page.

**Commands** (`scripts/kill_switch.py`; `--db` or `ALGO_DB_URL`):
```
show
pause|cancel|resume [--strategy ID] --by WHO --reason TEXT
flatten [--strategy ID] --by WHO --reason TEXT --emergency-override
```
`flatten` without the override is refused ("FLATTEN needs an explicit emergency override").

**When to pull it.** A reconciliation mismatch you do not understand; a wrong or runaway order; a data problem (bad prices, a corporate action not adjusted); the broker or exchange behaving oddly; anything where you want nothing new to happen while you look. Pause first, think second: it costs nothing and is reversible.

**Do this.**
1. `pause` (or `cancel` if approved orders are waiting and must not fill), with a reason that says what you saw.
2. Look: `show` for the history, the portal Risk page, `paper_reconcile.py`, the OMS log.
3. Fix the cause. 4. `resume` with a reason. 5. `show` and confirm RUNNING; run `scripts/platform_boot.py` if the platform state was changed.
A HALTED platform (set by a breach such as a reconciliation mismatch) is left only by an operator: `scripts/platform_boot.py --operator` after the cause is understood.

**Monthly drill** (TODO 5.7): run the sequence above on the dev or staging database and add a dated record to `docs/drills/`. **Drill record:** `docs/drills/2026-11-15-drills.md`.
