# Vinayak Trading Research Console

A read-only view of data, benchmark and research state. It is a presentation layer: no P&L, Sharpe,
fees, eligibility or corporate-action adjustment is calculated in the browser; every figure comes from
the API (`src/algo/api`), which serves what the backend already computed. Where the backend does not
store something yet (platform state, strategy lifecycle, job metrics) the console says so.

Screens: Dashboard, Data Explorer (raw / split-adjusted / total-return, labelled), Benchmarks,
Backtests (skeleton, controls disabled), System Activity.

    # terminal 1 (repo root)  - binds 127.0.0.1; there is no authentication
    ALGO_DB_URL=postgresql://postgres:dev@localhost:5433/algo make console-api
    # terminal 2
    cd frontend && npm install && npm run dev        # http://localhost:3000
    # checks
    make console-check

`NEXT_PUBLIC_API_URL` (default http://localhost:8000) points the console at the API.

Security notes: docs/console-security-review.md. Data check: `uv run python scripts/verify_console_data.py --db $ALGO_DB_URL`.

## Chart workspace

The Data Explorer is a full-height chart workspace laid out like a professional charting terminal: a top
bar (symbol search, 1D interval, candles/line/area, price basis, 1M-All range presets and a custom range,
undo/redo, object tree, PNG screenshot, full screen), a left tool rail with an icon per tool and flyout
menus (with hotkeys, e.g. Alt+T trend line, Alt+H horizontal line, Alt+F fib retracement), an in-chart
OHLC and volume legend, and a floating properties bar for the selected drawing.

## Chart drawing tools

22 tools in seven groups (Lines, Channels, Shapes, Fibonacci, Measure, Forecast, Annotation), in
`frontend/lib/drawings` (pure geometry, model, undo/redo - unit tested) and
`components/charts/DrawingTools.tsx` (toolbar, pointer handling, rendering). Select, drag a handle to
reshape, drag a drawing to move it, colour/width/style, lock, duplicate, delete, Delete/Esc/Ctrl+Z/Ctrl+Shift+Z,
magnet to open/high/low/close, hide all, an Objects list. Drawings are annotations saved in the browser
(localStorage) per instrument and price basis; they feed nothing else. Not TradingView's own toolkit
(that ships only with their licensed Advanced Charts product).
