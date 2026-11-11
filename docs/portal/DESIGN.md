# Portal design: authentication, users, per-user Kite, CRM, dashboards

Status: approved scope 2026-11-11. Deployment target: **internet-facing, several outside users**. Roles: Admin, Operator,
Trader, Viewer. Kite secrets: encrypted in the database, master key from the server environment. CRM scope: user
directory, activity timeline and audit trail, notes/tags/tasks, support tickets.

## 1. Threat model (what we defend against)
| threat | control |
|---|---|
| credential stuffing / brute force | Argon2id hashes; per-account and per-IP attempt limits with lockout; identical error and timing for unknown user and wrong password; weak-password refusal |
| stolen password | TOTP 2FA, **mandatory** for Admin and Operator, offered to everyone; hashed single-use recovery codes |
| session theft / fixation | opaque 256-bit tokens, only their SHA-256 stored; HttpOnly + Secure + SameSite=Lax cookie with the `__Host-` prefix; rotation on login, 2FA, password and role change; idle (30 min) and absolute (12 h) expiry; users can list and revoke sessions; a password change revokes all others |
| CSRF | SameSite cookie plus a per-session CSRF token required (header) on every state-changing request, plus an Origin check |
| XSS | no user HTML rendered; React escaping; CSP; secrets never sent to the browser after saving |
| privilege escalation / IDOR | deny by default; every route declares a permission; every object access is scoped by owner or role; a test enumerates all routes and asserts none is open |
| secret leakage (Kite key, secret, token) | AES-256-GCM per secret, AAD = owner + field, key ring with ids (rotation without downtime), master key only in the environment, write-only API (shows last 4 characters), every use audited, redacted from logs |
| tampering with history | audit log is append-only (database trigger refuses UPDATE/DELETE) and records actor, action, target, IP, user agent, request id |
| enumeration and info leaks | generic auth errors, no stack traces, rate limits on reset/invite endpoints, no user-existence oracle |
| operational | least-privilege database roles (read-only role for research queries, separate writable connection for portal tables), backups include the portal tables, health endpoint reveals nothing |

## 2. Architecture
- `src/algo/portal/` is a separate module: `passwords`, `totp`, `sessions`, `ratelimit`, `rbac`, `audit`, `users`, `vault`,
  `kite_connect`, `crm`, `dashboards`. Pure logic and SQL are separate; HTTP lives in `src/algo/api/portal_routes.py`.
- The browser talks only to the Next.js origin; Next rewrites `/api/*` to the backend, so cookies are same-origin and the
  API port is never public (no browser CORS with credentials).
- Existing research endpoints stay read-only and now require an authenticated principal with `research:read`.
- Tables are prefixed `portal_`, UUID ids for user-facing entities, all timestamps UTC `timestamptz`, numbered migrations
  (030 onward). Research queries keep the read-only session; portal writes use a separate writable connection.
- Tests: unit and integration, 100% line and branch coverage like the rest of `src/algo`. No auth-bypass flag exists in
  production code (tests override the principal dependency, the standard FastAPI way).

## 3. Roles and permissions (fixed set, deny by default)
| permission | Admin | Operator | Trader | Viewer |
|---|:-:|:-:|:-:|:-:|
| research:read (charts, data, benchmarks) | x | x | x | x |
| kite:own (own Kite connection) | x | x | x | |
| strategy:own (own strategies and runs) | x | | x | |
| ops:read (operational dashboard, pipeline) | x | x | | |
| ops:write (loader runs, review decisions) | x | x | | |
| users:read, users:write, roles:write | x | | | |
| crm:read, crm:write (notes, tags, tasks) | x | x | | |
| tickets:own (raise and read own tickets) | x | x | x | x |
| tickets:manage (all tickets) | x | x | | |
| audit:read | x | | | |
| system:settings | x | | | |

Rules: the last active Admin cannot be demoted, disabled or deleted; a user cannot change their own role; role changes
and suspension revoke the user's sessions at once.

## 4. Data model (`portal_*`)
- `portal_user`: id, email (normalised, unique), display_name, status INVITED|ACTIVE|SUSPENDED|DISABLED, role,
  password_hash, password_changed_at, must_change_password, totp_secret_enc, totp_enabled, failed_logins, locked_until,
  last_login_at, created_at, created_by.
- `portal_session`: id hash, user, csrf_hash, created, last_seen, expires, ip, user_agent, revoked_at.
- `portal_login_attempt`: email hash, ip, at, outcome. `portal_recovery_code`: user, hash, used_at.
- `portal_token`: invite and password-reset tokens (hash, purpose, expires, used_at).
- `portal_audit`: append-only. `portal_kite_connection`: user, api_key_enc, api_secret_enc, access_token_enc,
  token_expires_at, status, key_id.
- CRM: `portal_note`, `portal_tag`, `portal_user_tag`, `portal_task`, `portal_ticket`, `portal_ticket_message`.

## 5. Kite per user
Each Trader stores their own API key and secret (encrypted). Connecting: the portal builds the Kite login URL for that
user's key with a `state` bound to their session; Kite redirects to the callback registered on the user's Kite app; the
callback exchanges the request token server-side and stores the access token (it expires 06:00 IST daily and is shown as
"expires in ..."). A designated **system feed** connection (Admin-owned) later replaces the `.env` credentials used by
the data loaders.

## 6. Dashboards
- **User dashboard**: own Kite connection status and token expiry, own strategies and latest runs, own open tickets,
  security (2FA, active sessions, last logins).
- **Operational dashboard**: data freshness and coverage (bars, Kite fetch ledgers, failed windows), loader runs and token
  state of the system feed, API and database health, users by status and role, failed-login and lockout trends, open
  tickets, recent audit events.

## 7. Delivery phases (each shippable and fully tested)
1. **Auth core** (backend): schema, Argon2id, sessions, CSRF, rate limit and lockout, TOTP and recovery codes, RBAC,
   audit, login/logout/me/password endpoints; every existing `/api` route protected.
2. **Web login** (frontend): login and 2FA screens, session handling, route guards, account/security page, Next rewrite.
3. **User management**: invite, activate, roles, suspend, reset, session admin; the user directory (CRM list and profile).
4. **Kite vault and connect flow**.
5. **CRM**: timeline, notes, tags, tasks, tickets.
6. **Dashboards**: user and operational.
7. **Hardening pass**: CSP nonce, dedicated DB roles, dependency audit, abuse tests, runbook.

Out of scope until asked: order placement, billing, SSO/OAuth login, real email delivery (an outbox table and a mailer
interface are provided; a console mailer is the default).
