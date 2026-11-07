.PHONY: test cov lint type mut check
test: ; uv run pytest -q
cov:  ; uv run pytest -q -n auto --cov --cov-report=term-missing && uv run python scripts/check_floors.py
lint: ; uv run ruff check . && uv run ruff format --check .
type: ; uv run mypy src
mut:  ; uv run mutmut run
check: lint type cov
