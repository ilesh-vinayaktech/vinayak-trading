.PHONY: test cov lint type mut check quick console-check console-api dev-api dev-web dev-feed dev-admin
test: ; uv run pytest -q
cov:  ; uv run pytest -q -n auto --cov --cov-report=term-missing && uv run python scripts/check_floors.py
lint: ; uv run ruff check . && uv run ruff format --check .
type: ; uv run mypy src
mut:  ; uv run mutmut run
check: lint type cov
quick: ; uv run python scripts/quick_check.py $(ARGS)  # only what your change touches; `make quick ARGS=--list` shows the plan

console-check:
	cd frontend && npx tsc --noEmit && npx eslint . && npx vitest run && npx next build

console-api:
	uv run uvicorn --factory algo.api.main:build --host 127.0.0.1 --port 8000

# Development: the API reads .env (database, vault key, price source); the web app proxies /api to it.
dev-api:
	set -a; . ./.env; set +a; uv run uvicorn --factory algo.api.main:build --host 127.0.0.1 --port 8000 --reload
dev-web:
	cd frontend && npm run dev
dev-feed:
	set -a; . ./.env; set +a; uv run python scripts/feed_service.py
dev-admin:
	set -a; . ./.env; set +a; uv run python scripts/portal_create_admin.py --email "$(EMAIL)" --name "$(NAME)"
