# Runbook: no valid Kite session (token refresh failed)

**What it is.** Kite access tokens expire at 06:00 IST every day and Zerodha does not allow the login to be automated, so someone logs in each morning (the portal, or `scripts/kite_login.py`). The job `kite-login-reminder` runs Mon-Fri 08:15 IST and raises the alert when no session is valid before the feed starts.

**The alert.** `kite-login-reminder: SKIPPED, no valid Kite session (log in via the portal; tokens expire 06:00 IST)`; the job exits 75 (the runner's "skipped" code). The same alert and exit appear for the two other jobs that need a session (`kite-daily-candles`, `kite-daily-revise`); they skip, they do not fail or retry.

**What stays safe without a session.** Nothing trades: the live gate (`execution/live_gate.py`) refuses live mode unless `ALGO_LIVE=1`, the strategy is in the LIVE stage, **there is a valid broker session**, and every regulatory rule is recorded and recently verified; anything else is paper. The platform boot (`scripts/platform_boot.py`) only reaches READY when a valid session is among its probes, so the platform stays out of PAPER/LIVE and strategies cannot emit targets (`platform_state/store.trading_blocked`). The live feed's own heartbeat goes quiet, which `check_heartbeats.py` reports.

**Do this.**
1. Log in: portal (preferred) or `uv run python scripts/kite_login.py` (prints a URL; sign in with 2FA; paste the redirected address or the `request_token`; the token is saved to `data/secrets/kite_token.json`, owner-only, never printed). Add `--force` to log in again while a saved token is still valid.
2. Check: `uv run python scripts/run_job.py kite-login-reminder` must now exit 0 without an alert.
3. Check the feed is back: `uv run python scripts/check_heartbeats.py` (exit 0, "0 problem(s)").
4. Re-boot the platform: `uv run python scripts/platform_boot.py` (exit 0 only when it ends in PAPER or LIVE). A platform that went HALTED is not restarted by this; see the kill-switch runbook (`--operator`).
5. Catch up what was skipped: `kite-daily-candles` and `kite-daily-revise` run again at their next slot; run them by hand with `scripts/run_job.py NAME` if the day matters.

**If the login itself fails.** Wrong or expired API key/secret: check the Kite developer console and `.env`; Zerodha down or 2FA failing: nothing in this system can work around it, wait or call Zerodha; request_token already used: it is single use, log in again from the URL. Do NOT paste tokens into chat or tickets.

**Drill record:** `docs/drills/2026-11-15-drills.md`.
