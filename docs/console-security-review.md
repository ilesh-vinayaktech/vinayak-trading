# Research console: API and web security review (2026-11-08)

Scope: `src/algo/api` (FastAPI, read-only) and `frontend/` (Next.js). Local research tool, no users.

**There is no authentication or authorization.** CORS limited to `http://localhost:3000` is a browser
rule, not access control: any local process can call the API directly. Therefore:
- both servers bind to loopback (`uvicorn --host 127.0.0.1`, `next ... -H 127.0.0.1`; verified with
  `ss -ltn`: 127.0.0.1:8000 and 127.0.0.1:3000);
- never expose either port, or run them on 0.0.0.0, without an authenticating reverse proxy in front.

Controls in place (each covered by a test in `tests/integration/test_app.py` / `tests/unit/test_main.py`):
| risk | control |
|---|---|
| writes through the API | no write endpoints (GET only; POST returns 405); every DB session is `default_transaction_read_only=on` |
| runaway queries | `statement_timeout` 15 s, `idle_in_transaction_session_timeout` 30 s, connect timeout 5 s |
| SQL injection | every query is parameterised; `%`, `_` and `\` in a search term are escaped (a `%` search returns nothing) |
| oversized responses | search `limit` <= 100, `q` <= 64 chars, bar range <= 40 years, level points <= 10 000, activity and backtest pages <= 200 |
| information leakage | interactive docs and the OpenAPI schema are off unless `ALGO_API_DOCS=1`; health reports only the exception class; unhandled errors are a generic 500 |
| clickjacking / sniffing / caching | API and pages send `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`; API responses `Cache-Control: no-store`; pages send a CSP (`frame-ancestors 'none'`, `connect-src` limited to the API) and `X-Powered-By` is removed |
| cross-origin reads | CORS allows only the configured origins, GET only, no credentials |

Residual risks, not fixed here:
- the API connects as the same database role as the rest of the platform. Create a dedicated role
  (`CREATE ROLE console LOGIN; GRANT CONNECT ON DATABASE algo TO console; GRANT USAGE ON SCHEMA public
  TO console; GRANT SELECT ON ALL TABLES IN SCHEMA public TO console;`) and put its DSN in
  `ALGO_DB_URL`; the read-only session setting is a second line of defence, not the first;
- no rate limiting; no per-request audit log;
- the CSP allows inline scripts/styles because Next.js hydration needs them (no nonce yet);
- `/api/backtests/{id}` returns the stored configuration verbatim: fine locally, review before any
  shared deployment.

Data verification: `scripts/verify_console_data.py` re-derives 69 figures from the database and the frozen
release files and compares them with the API (all equal); a browser check compared 82 rendered values
with the API.
