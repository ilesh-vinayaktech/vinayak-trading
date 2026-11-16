# Deploy to production, from a blank server

Written for the owner, who runs every command. Each step says what it does and how to check it worked. Nothing here has been run on a
production server yet: the commands are taken from this repository (`start_all.sh`, `Makefile`, `docs/runbooks/`, `scripts/`), and the parts
that are NOT in the repository are marked **[not tested]** and listed in section 15. Do the steps in order; do not skip a check.

Mode on day one is **PAPER**. Real orders stay impossible until section 12 is done on purpose.

---

## 0. What you are deploying

| Piece | What it is | Port (loopback only) |
|---|---|---|
| Database | TimescaleDB (PostgreSQL 16) in Docker, database `algo` | 5433 -> container 5432 |
| API | FastAPI: `uvicorn --factory algo.api.main:build` | 8000 |
| Web | Next.js console, proxies `/api/*` to the API | 3000 |
| Study worker | `scripts/study_worker.py`: runs backtest studies, one at a time (about 2 GB of memory) | none |
| Feed | `scripts/feed_service.py --wait`: Kite WebSocket to 1-minute bars on trading days | none |
| Scheduled jobs | systemd timers written by `scripts/install_job_timers.py` (bhavcopy, reconcile, paper run, backups ...) | none |
| Raw data lake | `data/lake`, about 11 GB, append-only files | none |

Only the reverse proxy (section 8) listens on the public internet. The API and web app must stay on `127.0.0.1`.

## 1. What the server needs

- Ubuntu 22.04 or 24.04 LTS, x86-64. **At least 8 GB of memory (16 GB recommended: one study worker alone is about 2 GB, and the database, API and a
  compute job run at the same time), 4 cores, 100 GB of disk** (lake 11 GB + database about 40 GB + nightly dumps 4.6 GB x 14).
- A **static public IPv4 address**. Zerodha only accepts orders from the IP registered for your Kite app; you said the static IP is the one thing
  still missing for live trading. Paper trading and data do not need it.
- A domain name (for example `algo.yourdomain.com`) with an A record to that IP, for HTTPS.
- Your Zerodha Kite Connect app (API key and secret) and its **redirect URL** (section 9).
- Outbound internet to NSE, Zerodha and the other sources the jobs read.

## 2. Prepare the server

As a sudo user on the server:

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install git curl ca-certificates ufw docker.io postgresql-client rsync
sudo systemctl enable --now docker

# Node 22 LTS (the console uses Next 15, which needs Node 18.18 or newer)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt -y install nodejs

# a dedicated user that runs everything (no sudo)
sudo adduser --disabled-password --gecos "" algo
sudo usermod -aG docker algo
sudo loginctl enable-linger algo        # so this user's timers and services run when nobody is logged in
```

Firewall: only SSH and web.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
sudo ufw status                          # check: 22, 80, 443 only. NOT 3000, 8000, 5433.
timedatectl status                       # check: "System clock synchronized: yes"
```

(The code stores every date in UTC and the jobs name `Asia/Kolkata` themselves, so the server's own time zone does not matter.)

Install `uv` (the Python package manager) as the `algo` user:

```bash
sudo -iu algo
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

Check, as `algo`: `uv --version`, `node --version`, `docker ps` (no error).

## 3. Get the code

```bash
sudo -iu algo
mkdir -p ~/Work && cd ~/Work
git clone <your repository URL> trading
cd trading
git log --oneline | head -3              # check: the commit you expect
export PATH="$HOME/.local/bin:$PATH"
uv sync                                  # creates .venv with Python 3.12 and every dependency from uv.lock
(cd frontend && npm ci)                  # the console's packages from the lockfile
```

Use the folder name `trading` exactly: the feed unit and the crontab in `infra/` assume `~/Work/trading`.

## 4. Start the database

A strong password, kept in a file only `algo` can read (never in the repository):

```bash
cd ~/Work/trading
mkdir -p data/secrets && chmod 700 data/secrets
openssl rand -base64 24 | tr -d '/+=' > data/secrets/pg_password && chmod 600 data/secrets/pg_password

docker volume create algo_pgdata
docker run -d --name algo-dev --restart unless-stopped \
  -e POSTGRES_PASSWORD="$(cat data/secrets/pg_password)" -e POSTGRES_DB=algo \
  -v algo_pgdata:/var/lib/postgresql/data \
  -p 127.0.0.1:5433:5432 \
  timescale/timescaledb:2.17.2-pg16
```

The container is called `algo-dev` on purpose: `start_all.sh`, the backup job and the runbooks all use that name. `-p 127.0.0.1:5433:5432` binds the
database to loopback only. The image tag is the one `docker-compose.dev.yml` uses.

Check: `docker ps` shows it Up; `docker exec algo-dev pg_isready -U postgres` says "accepting connections".

## 5. Configure the environment

```bash
cd ~/Work/trading
cp .env.example .env && chmod 600 .env
```

Edit `.env`. Every value below must be set; leave nothing from the development defaults:

```bash
ALGO_DB_URL=postgresql://postgres:<the password in data/secrets/pg_password>@127.0.0.1:5433/algo
ALGO_PRICE_SOURCE=kite
ZERODHA_API_KEY=<from your Kite Connect app>
ZERODHA_API_SECRET=<from your Kite Connect app>

# the key ring that encrypts every stored secret (each user's broker keys). GENERATE A NEW ONE FOR PRODUCTION and back it up OFFLINE:
#   python3 -c "import os,base64;print('v1:'+base64.b64encode(os.urandom(32)).decode())"
ALGO_VAULT_KEYS=<the generated v1:... value>
ALGO_VAULT_CURRENT=v1

# production: secure cookies stay ON (delete the ALGO_COOKIE_SECURE=0 line from the development file), the proxy is trusted
ALGO_TRUST_PROXY=1
ALGO_PUBLIC_URL=https://algo.yourdomain.com
ALGO_CORS_ORIGINS=https://algo.yourdomain.com

# alerts: a failed or stale job tells you (otherwise it only reaches the system journal)
ALGO_TELEGRAM_TOKEN=<bot token>
ALGO_TELEGRAM_CHAT=<chat id>

# off-server copy of the raw lake (section 11)
ALGO_LAKE_BACKUP_DIR=<a mounted directory on OVH object storage or another disk>
```

Leave **unset**: `ALGO_COOKIE_SECURE`, `ALGO_LIVE`, `ALGO_MODE`, `ALGO_LIVE_CONFIRM`, `ALGO_API_DOCS`, `ALGO_REVIEW_WRITES`. Real orders need
`ALGO_MODE=live` AND the exact confirmation phrase AND more (section 12); a missing variable can never switch them on.

**The vault key is the one thing you cannot regenerate.** If it is lost, every stored broker credential is unreadable and each user must re-enter
theirs. Keep a copy offline (a password manager), separate from the server and from the database backups.

## 6. Create the schema and the first administrator

```bash
cd ~/Work/trading
export PATH="$HOME/.local/bin:$PATH"
set -a; . ./.env; set +a
uv run python - <<'PY'
import os, psycopg
from algo.data.store.migrate import migrate
with psycopg.connect(os.environ["ALGO_DB_URL"], autocommit=True) as c:
    print("applied:", migrate(c))
PY
make dev-admin EMAIL=you@yourdomain.com NAME="Your Name"
```

`migrate` applies every numbered file in `src/algo/data/store/migrations/` (about 85) and records each; running it again is safe and prints an
empty list. `dev-admin` asks for a password on the terminal (never on the command line) and the administrator must enrol a second factor at first
sign-in.

Check: `docker exec algo-dev psql -U postgres -d algo -c "select count(*) from portal_user"` returns 1.

## 7. Load the data

A server built from scratch has an empty database. **Do not rebuild it from the internet**: the history comes from many sources over years, a rebuild
takes days, and some sources (the old NSE feeds) cannot be reproduced on demand. Copy it from the development machine instead.

On the development machine (the nightly `db-backup` job already writes the dump; run it now to be current):

```bash
cd ~/Work/vinayak/vinayak-trading
export PATH=$HOME/.local/bin:$PATH
set -a; . ./.env; set +a
uv run python scripts/run_job.py db-backup          # writes data/backups/algo_<date>.dump (about 4.6 GB)
ls -lh data/backups | tail -2
rsync -avP data/backups/algo_<date>.dump algo@SERVER:~/Work/trading/data/backups/
rsync -avP --ignore-existing data/lake/ algo@SERVER:~/Work/trading/data/lake/   # about 11 GB; --ignore-existing because the lake is append-only
```

(Create `~/Work/trading/data/backups` on the server first if `rsync` says it is missing.)

On the server, restore into an empty `algo` database. TimescaleDB needs its pre/post calls around `pg_restore`; this is the procedure verified in
`docs/runbooks/restore-from-backup.md` (4.8 GB in about 14 minutes):

```bash
cd ~/Work/trading
D=data/backups/algo_<date>.dump
docker exec algo-dev psql -U postgres -c "drop database algo" -c "create database algo"
docker exec algo-dev psql -U postgres -d algo -c "create extension if not exists timescaledb" -c "select timescaledb_pre_restore()"
docker exec -i algo-dev pg_restore -U postgres -d algo --no-owner < $D
docker exec algo-dev psql -U postgres -d algo -c "select timescaledb_post_restore()"
```

This **replaces** the schema and the administrator made in section 6: the restored database carries the development machine's users. Sign in with an
existing account there, or run `make dev-admin` again after the restore.

Verify before trusting it. Run the row-count query from `docs/runbooks/restore-from-backup.md` on both machines and compare: the server may be lower
only if the dump is older than the latest write, never higher. Then:

```bash
./start_all.sh                               # applies any newer migrations, starts api, web, worker, feed (for the first check only; section 10 replaces it)
uv run python scripts/check_stale.py         # the data-freshness verdict
./start_all.sh stop
```

Then catch the data up to today: `uv run python scripts/run_job.py bhavcopy-daily`, then `uv run python scripts/run_job.py gap-nightly`.

## 8. HTTPS reverse proxy [not tested: nothing in the repository configures this]

The console has its own sign-in (password plus second factor), but it must be reached over HTTPS only. Caddy gets and renews the certificate itself:

```bash
sudo apt -y install caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
algo.yourdomain.com {
    reverse_proxy 127.0.0.1:3000
}
EOF
sudo systemctl reload caddy
```

Only the web app is proxied: it already forwards `/api/*` to the API on loopback, so the browser sees one origin and the session cookie stays
same-site (`frontend/next.config.mjs`). Caddy appends the real client address to `X-Forwarded-For`, which is what `ALGO_TRUST_PROXY=1` expects. Do not
proxy port 8000 directly.

Check: `https://algo.yourdomain.com` shows the sign-in page with a valid certificate; from another machine `curl -m 5 http://SERVER_IP:3000` and
`:8000` fail.

## 9. Kite Connect

1. In the Kite Connect developer console set the app's **redirect URL** to `https://algo.yourdomain.com/kite/callback` (the code builds
   `ALGO_PUBLIC_URL + /kite/callback`; see `src/algo/portal/kite_vault.py`).
2. Register the server's **static IP** for the app (needed for orders, not for data).
3. Sign in to the console, open the Kite page, press Connect, finish Zerodha's login (password and 2FA), then "Use my connection as the data feed".

**Kite's login cannot be automated, by design.** The token it gives dies at 06:00 IST the next day. So every trading morning, before 08:15 IST (when
`kite-login-reminder` alerts you), do step 3 again. If you forget, the feed waits and checks every 30 seconds; see
`docs/runbooks/kite-token-refresh-failure.md`.

## 10. Run it as services that survive a reboot [not tested]

`start_all.sh` is a development convenience (background processes and pid files). On a server use systemd. As `algo`:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/algo-api.service <<'EOF'
[Unit]
Description=Algo API
After=network-online.target
[Service]
WorkingDirectory=%h/Work/trading
ExecStart=/bin/bash -c 'set -a; . ./.env; set +a; exec %h/.local/bin/uv run uvicorn --factory algo.api.main:build --host 127.0.0.1 --port 8000'
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
EOF
cat > ~/.config/systemd/user/algo-web.service <<'EOF'
[Unit]
Description=Algo console (Next.js)
After=algo-api.service
[Service]
WorkingDirectory=%h/Work/trading/frontend
ExecStart=/usr/bin/env npx next start -H 127.0.0.1 -p 3000
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
EOF
cat > ~/.config/systemd/user/algo-worker.service <<'EOF'
[Unit]
Description=Algo study worker
After=algo-api.service
[Service]
WorkingDirectory=%h/Work/trading
ExecStart=/bin/bash -c 'set -a; . ./.env; set +a; exec %h/.local/bin/uv run python scripts/study_worker.py'
Restart=on-failure
RestartSec=30
[Install]
WantedBy=default.target
EOF
```

Build the console once, then enable. The feed unit and its timer are in the repository (`infra/systemd/algo-feed.*`); copy them as they are, their
`WorkingDirectory=%h/Work/trading` matches section 3:

```bash
(cd frontend && NODE_OPTIONS=--max-old-space-size=3072 npx next build)
cp infra/systemd/algo-feed.service infra/systemd/algo-feed.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now algo-api algo-web algo-worker
systemctl --user enable --now algo-feed.timer
systemctl --user status algo-api algo-web algo-worker --no-pager
```

Check: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/intel/progress` prints 401 (the API answers and wants a sign-in);
`curl -sI http://127.0.0.1:3000 | head -1` prints 200 or 307.

Do not stop the worker while a study is RUNNING.

## 11. The scheduled jobs and backups

The repository already defines every job (`src/algo/jobs/registry.py`): the daily bhavcopy at 18:30 IST, completeness, platform boot before the open,
paper run/orders/reconcile, the nightly `db-backup` at 23:00, `lake-backup`, the weekly calendar and more. Install their timers:

```bash
cd ~/Work/trading
export PATH="$HOME/.local/bin:$PATH"
uv run python scripts/install_job_timers.py       # writes the units and PRINTS the enable commands: run exactly the lines it prints
systemctl --user daemon-reload
# then, for each job it listed:  systemctl --user enable --now algo-job-<name>.timer
systemctl --user list-timers | grep algo
```

**The paper-trading timers (`paper-run`, `paper-orders`, `paper-reconcile`) are the item still waiting for your decision.** Enable them only when you
want paper orders proposed every day.

Backups, so a dead server is not the end:
1. `ALGO_LAKE_BACKUP_DIR` in `.env` points at storage that is NOT this server's disk (OVH object storage mounted, or another machine); the
   `lake-backup` job mirrors the lake there, add-only and verified, and alerts until a destination is set.
2. Copy `data/backups/*.dump` off the server as well (the nightly dump is on the same disk): for example a daily `rsync` to the same place.
3. **Test a restore** with the "throwaway database" procedure in `docs/runbooks/restore-from-backup.md` before you depend on it.
4. The vault key (section 5) is stored offline.

## 12. Turning on real orders (leave this for later)

Real orders need all of these at once (`src/algo/execution/live_gate.py`, `src/algo/core/settings.py`): `ALGO_MODE=live` with the exact
`ALGO_LIVE_CONFIRM` phrase, `ALGO_LIVE=1`, a strategy promoted to the LIVE stage, a valid broker session, and the regulatory rules recorded and
verified lately (`scripts/regulatory.py`). The plan requires at least 8 uninterrupted weeks of paper trading with zero unreconciled differences first
(TODO 5.7). Practise the emergency stop before the first live day: `docs/runbooks/kill-switch.md`
(`scripts/kill_switch.py pause|cancel|flatten`).

## 13. Final acceptance checklist

Tick every line before you rely on the server.

- [ ] `sudo ufw status` shows only 22, 80, 443; from another machine, ports 3000, 5433 and 8000 are closed.
- [ ] HTTPS works with a valid certificate; plain HTTP redirects.
- [ ] You can sign in with the administrator and the second factor works.
- [ ] `docker exec algo-dev pg_isready` is OK and the row counts match the development machine.
- [ ] `systemctl --user status algo-api algo-web algo-worker` are all active; **reboot the server once** and they come back by themselves.
- [ ] `uv run python scripts/check_stale.py` is clean after `bhavcopy-daily`.
- [ ] After the Kite login, the console shows a live feed during market hours and the platform reaches PAPER (`scripts/platform_boot.py`).
- [ ] A Telegram alert arrives (for example run `uv run python scripts/run_job.py kite-login-reminder` with no Kite session).
- [ ] A nightly `db-backup` ran, the dump was restored into a throwaway database and matched, and a copy sits off the server.
- [ ] The vault key exists in two places that are not this server.
- [ ] `git status` on the server is clean and `git log -1` is the commit you meant to deploy.

## 14. Updating later

```bash
sudo -iu algo && cd ~/Work/trading && export PATH="$HOME/.local/bin:$PATH"
git pull --ff-only
uv sync && (cd frontend && npm ci)
systemctl --user stop algo-web                    # stop the worker too only if no study is RUNNING
set -a; . ./.env; set +a
uv run python -c "import os,psycopg; from algo.data.store.migrate import migrate; print(migrate(psycopg.connect(os.environ['ALGO_DB_URL'], autocommit=True)))"
(cd frontend && NODE_OPTIONS=--max-old-space-size=3072 npx next build)
systemctl --user restart algo-api algo-worker && systemctl --user start algo-web
```

The API and the worker read the code once, at start: **a running process keeps the old code until it is restarted** (this is what hid new pages on
the development machine). Run the tests on the development machine first (`make check`), never on the server.

## 15. What I could not verify from the repository

These are the gaps in this document, so you can judge the risk:

1. **Sections 8 and 10 are new, not taken from the repository** (Caddy and the api/web/worker systemd units). They follow the repository's own commands
   but have not been run on a server.
2. **No production machine has ever run this.** Expect to fix small things (paths, permissions) on the first pass: rehearse on a throwaway server.
3. **Kite login end to end** was never exercised on a public address: `/kite/callback` is a page of the web app itself (`frontend/app/kite/callback`), so the
   proxy needs no extra rule, but test the full login in section 9 before relying on it.
4. **`docs/console-security-review.md` (2026-11-08) says the console has no authentication.** It predates the portal sign-in (accounts, password,
   second factor). Treat that page as history; the sign-in from section 6 is what protects the console. It also advises a separate read-only
   database role for the API, which is not done: every service uses one database role.
5. **Server size and the OVH product** are your call; the numbers in section 1 come from this machine's measured memory use, not from a load test.
6. **Order IP:** live orders need the static IP registered in Kite; I could not check Zerodha's current rules from here.
