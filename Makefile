.PHONY: test cov lint type mut check console-check console-api
test: ; uv run pytest -q
cov:  ; uv run pytest -q -n auto --cov --cov-report=term-missing && uv run python scripts/check_floors.py
lint: ; uv run ruff check . && uv run ruff format --check .
type: ; uv run mypy src
mut:  ; uv run mutmut run
check: lint type cov

console-check:
	cd frontend && npx tsc --noEmit && npx eslint . && npx vitest run && npx next build

console-api:
	uv run uvicorn --factory algo.api.main:build --host 127.0.0.1 --port 8000
