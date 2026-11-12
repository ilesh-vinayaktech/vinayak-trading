#!/usr/bin/env bash
# Start (or stop, or check) everything the platform needs, in the right order. Safe to run again: anything already running
# is left alone.
#
#   ./start_all.sh            start what is not running
#   ./start_all.sh status     show what is running
#   ./start_all.sh stop       stop the API, web app, worker and feed (the database container is left running)
#   ./start_all.sh rebuild    rebuild the web app (needed after any frontend change), then restart it
#
# Pieces: database (docker "algo-dev") -> migrations -> API :8000 -> web app :3000 -> study worker -> live feed.
# Logs: .run/logs/*.log   Process ids: .run/*.pid
set -uo pipefail
cd "$(dirname "$0")"

DB_CONTAINER=algo-dev
RUN=.run
mkdir -p "$RUN/logs"

say() { printf '%s\n' "$*"; }
load_env() { set -a; . ./.env; set +a; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# true if a process whose command line contains $1 is already running (started by hand, not by this script)
elsewhere() { pgrep -f -- "$1" >/dev/null 2>&1; }

# name, command...  -> runs it in the background with .env loaded, remembers its pid
launch() {
  local name=$1; shift
  if alive "$name"; then say "  $name: already running (pid $(cat "$RUN/$name.pid"))"; return; fi
  ( load_env; setsid nohup "$@" >>"$RUN/logs/$name.log" 2>&1 & echo $! >"$RUN/$name.pid" )
  say "  $name: started (log .run/logs/$name.log)"
}

wait_port() {  # port, seconds
  for _ in $(seq 1 "$2"); do port_open "$1" && return 0; sleep 1; done
  return 1
}

db_running() { [ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null)" = "true" ]; }

start_db() {
  if db_running; then
    say "  database: already running"
  else
    say "  database: starting container $DB_CONTAINER"
    docker start "$DB_CONTAINER" >/dev/null || { say "  database: could not start $DB_CONTAINER"; exit 1; }
    sleep 5
  fi
}

migrate() {
  load_env
  uv run python - <<'PY'
import os, psycopg
from algo.data.store.migrate import migrate
with psycopg.connect(os.environ["ALGO_DB_URL"], autocommit=True) as c:
    done = migrate(c)
    print("  migrations:", ", ".join(done) if done else "up to date")
PY
}

build_web() {
  say "  web: building (a minute or two)"
  ( cd frontend && NODE_OPTIONS=--max-old-space-size=3072 npx next build >"../$RUN/logs/web-build.log" 2>&1 ) \
    || { say "  web: build failed, see .run/logs/web-build.log"; exit 1; }
}

start_web() {
  if alive web; then say "  web: already running (pid $(cat "$RUN/web.pid"))"; return; fi
  if port_open 3000; then say "  web: port 3000 is already in use (started by hand?), leaving it"; return; fi
  [ -d frontend/.next ] || build_web
  ( cd frontend; setsid nohup npx next start -p 3000 >>"../$RUN/logs/web.log" 2>&1 & echo $! >"../$RUN/web.pid" )
  say "  web: started on http://localhost:3000 (log .run/logs/web.log)"
}

stop_one() {
  local name=$1
  if alive "$name"; then
    kill -- "-$(cat "$RUN/$name.pid")" 2>/dev/null  # the whole process group: npx and uv start children
    say "  $name: stopped"
  else
    say "  $name: not running"
  fi
  rm -f "$RUN/$name.pid"
}

status() {
  for n in api web worker feed; do
    if alive $n; then say "  $n: running (pid $(cat "$RUN/$n.pid"))"; else say "  $n: not running"; fi
  done
  if port_open 8000; then say "  port 8000 (API): open"; else say "  port 8000 (API): closed"; fi
  if port_open 3000; then say "  port 3000 (web): open"; else say "  port 3000 (web): closed"; fi
  if db_running; then say "  database: running"; else say "  database: not running"; fi
}

SERVICES="db api web worker feed"

start_api() {
  if port_open 8000 && ! alive api; then say "  api: port 8000 is already in use (started by hand?), leaving it"; return; fi
  launch api uv run uvicorn --factory algo.api.main:build --host 127.0.0.1 --port 8000
  wait_port 8000 20 || say "  api: not answering yet, check .run/logs/api.log"
}

start_worker() {
  if elsewhere "scripts/study_worker.py" && ! alive worker; then say "  worker: already running (started by hand), leaving it"; return; fi
  launch worker uv run python scripts/study_worker.py
}

start_feed() {
  if elsewhere "scripts/feed_service.py" && ! alive feed; then say "  feed: already running (started by hand), leaving it"; return; fi
  launch feed uv run python scripts/feed_service.py --wait
}

stop_db() {
  if db_running; then docker stop "$DB_CONTAINER" >/dev/null && say "  database: stopped"; else say "  database: not running"; fi
}

check_service() {
  case " $SERVICES " in *" $1 "*) ;; *) say "unknown service '$1' (one of: $SERVICES)"; exit 1 ;; esac
}

start_one() {
  check_service "$1"
  case $1 in
    db) start_db ;;
    api) start_db; start_api ;;
    web) start_web ;;
    worker) start_worker ;;
    feed) start_feed ;;
  esac
}

stop_svc() {
  check_service "$1"
  if [ "$1" = db ]; then stop_db; else stop_one "$1"; fi
}

case "${1:-start}" in
  start)
    if [ -n "${2:-}" ]; then say "Starting $2:"; start_one "$2"; exit 0; fi
    say "Starting:"
    start_db
    migrate
    start_api
    start_web
    start_worker
    start_feed
    say "Open http://localhost:3000"
    ;;
  status) say "Status:"; status ;;
  stop)
    if [ -n "${2:-}" ]; then say "Stopping $2:"; stop_svc "$2"; exit 0; fi
    say "Stopping:"
    for n in feed worker web api; do stop_one $n; done  # the database is left running; stop it by name
    ;;
  restart)
    if [ -z "${2:-}" ]; then say "usage: $0 restart <service>   (one of: $SERVICES)"; exit 1; fi
    say "Restarting $2:"
    stop_svc "$2"
    sleep 1
    start_one "$2"
    ;;
  rebuild)
    say "Rebuilding the web app:"
    stop_one web
    build_web
    start_web
    ;;
  *)
    say "usage: $0 start|stop [service]   restart <service>   status   rebuild"
    say "services: $SERVICES"
    exit 1
    ;;
esac
