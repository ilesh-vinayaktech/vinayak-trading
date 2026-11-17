# Data inventory (2026-11-17)

What we hold in the main database, how much, how far back, who reads it today, and what it could feed. Counts are from the
full database (not `pg_stat` estimates, which were stale). Part of TODO Stage 6.1. "Read by" lists the `src/algo` packages
that touch the table; a table read only by `data`/`research` is data the portal never shows and no strategy uses.

## Prices and market structure

| Data | Rows | Range | Read by | What is missing or unused | Could feed |
|---|---:|---|---|---|---|
| `bar_1d` daily bars, all stocks | 7.58M | 2016-01 .. today | alpha, api, features, paper, research, screener | `delivery_qty` on only 2.87M rows (38%); no gaps list in the UI | scores, trend, breadth, S/R, volume profile |
| `bar_1m` minute bars | 397.7M | 2016-01 .. today | data, research only | the portal never reads it | intraday S/R, opening-range, volume-at-price histograms, intraday seasonality |
| `live_bar_1m`, `live_quote` | 1.94M / 2.6k | 2026-11-12 .. today | api, live, paper | only the order price check uses it | live breakout alerts, live prediction |
| `index_bar_1d` | 876k, 205 series | 1990 .. today | **data only** | not shown anywhere; includes **INDIA VIX** and 25+ sector indices (Bank, IT, Pharma, Auto, FMCG, Metal, Realty, Energy, PSU Bank, Fin Services, ...) | market zone, fear/greed, sector rotation, relative strength |
| `benchmark_observation` (TRI etc.) | 155k | long | api, backtest, data, portfolio, research | | benchmark and alpha |
| `corporate_action`, `_upcoming` | 24.9k / 22 | 2005 .. 2026-11-25 | api, data, research, screener | | event flags, adjusted S/R |
| `market_cap_rank` / `_list` | 86k / 17 | period lists | data, research, screener | | size class, liquidity tiers |
| `index_membership_*`, `index_monthly_*`, `index_release_*` | 600 to 146k | 2017 .. 2026-10 | data, research | the monthly files carry **88 industry labels** for 45.6k rows | derive the sector map (see gaps) |

## Smart money and ownership

| Data | Rows | Range | Read by | What is missing or unused | Could feed |
|---|---:|---|---|---|---|
| `nse_shareholding` (promoter, public, FII, DII %) | 46k | periods 2018-03 .. 2026-11 | api, data, screener | only as snapshot fields; no holding-trend score or timeline | quarter-on-quarter change, accumulation, promoter pledge-type flags |
| `nse_bulk_block_deal` | 166k | 2016 .. 2026-11-16 | api, data, screener | no net-flow score, no client track record | net buy/sell per stock and day, repeat buyers, size vs volume |
| `nse_insider_trade` | 342k | 2019 .. 2026 (12 rows have impossible dates) | api, data, screener | no insider score; bad dates need a filter | net insider value, cluster buying, role weighting |
| `nse_insider_filing` | 3.5k | 2026-05 .. today | **data only** | not shown | filing timeliness, late-filer flag |
| `nse_fii_dii` market flows | **2** | one day | api, data | **no history**, so no flow trend | FII/DII regime input (needs a backfill source: parked) |

## Fundamentals

| Data | Rows | Range | Read by | Notes |
|---|---:|---|---|---|
| `fundamental_filing` | 48k filings | filed 2018-05 .. today | api, data, features, research, screener | 5.6k more are known but not loaded (`fundamental_unloaded`) |
| `fundamental_fact` | 7.79M facts | | api, data, research, screener | feeds the 20 `fund_*` features and the screener ratios |

## Computed features and the screener

| Data | Rows | Range | Read by | Notes |
|---|---:|---|---|---|
| `feature_value` (35 features: returns 1d..252d, RSI, ATR, distance from SMA and 52-week high/low, volume ratio, drawdown, volatility, 20 fundamental ratios) | **49.2M** | 2017-12 .. **2024-12-31** | alpha, features | stops at the development-window end, not refreshed to today; the portal and screener do not use it |
| `screener_snapshot` | 2.6k (today's row per stock) | rebuilt daily | screener | about 60 fields per stock already: price changes 1d..1y, RSI, ADX, MACD hist, SMA position, volume ratio, delivery % and 20-day delivery, 52-week position, PE/PB/ROE/ROCE/margins, FII/DII/promoter % and change, sector, market cap |

## Gaps and fixes found

1. **Sector map is empty**: `instrument_sector` has 0 rows, yet the snapshot has a `sector`. Derive a single map from the monthly constituent industry labels (88 industries) and the sector indices, and store it (Stage 6.4).
2. **No FII/DII history**: 2 rows. Parked for the owner (source or backfill).
3. **No news, no option-chain/PCR, no advance-decline from the exchange**: advance-decline and breadth can be computed from `bar_1d`; news is Stage 6.7; PCR and option chain are parked.
4. **`feature_value` ends 2024-12-31**: a live score layer needs the same features computed to today, point in time.
5. **Insider dates**: 12 of 342k rows have impossible dates; filter in the reader and report.
6. **Delivery**: only 38% of daily bars carry `delivery_qty`; the score must handle missing values and say so.
7. **Unused by the portal**: `index_bar_1d`, `bar_1m`, `nse_insider_filing`, `feature_value`. These are the first places to get value from.
