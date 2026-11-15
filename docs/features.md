# Features (generated: do not edit; `uv run python scripts/feature_docs.py write`)

Price and volume features only (Phase 1). A feature is identified by name and version; its `manifest_sha256` covers the manifest, the source of its module and of every
declared helper, so a change to any of them needs a NEW version (`config/feature_manifests.json` and `store.register_all` refuse otherwise). A feature can be named in a
study only when its status is USABLE, which `scripts/validate_features.py` sets after a stored, passed validation report.

Common rules, stated in every manifest:

- **adjustment**: split and bonus adjusted, point in time as of the feature day (BarReader mode 'split'); traded value uses raw close and raw volume
- **missing_data**: a window containing a session with no bar gives no value; nothing is interpolated or filled; a value inside its warm-up is absent, never zero
- **availability**: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- **session_rule**: a session is a day on which at least half of the dataset's instruments have a bar
- **precision**: values are quantised to 12 decimal places (half-even)

## ret_5d (version 1)

- Definition: close[t] / close[t-n] - 1
- Formula `ret`, parameters {'n': 5}, inputs close, unit fraction
- Warm-up: 6 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `11ccd725799cae949a4366e2e3e42d27bfe6369f3875de264cdc9f6fa7977619`
- Version history:
  - 1 (2026-11-15): first version.

## ret_20d (version 1)

- Definition: close[t] / close[t-n] - 1
- Formula `ret`, parameters {'n': 20}, inputs close, unit fraction
- Warm-up: 21 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `e048db355ded69752d9838acdaf26501d49b5953779ddc2b17c80aae9ac63e7c`
- Version history:
  - 1 (2026-11-15): first version.

## ret_60d (version 1)

- Definition: close[t] / close[t-n] - 1
- Formula `ret`, parameters {'n': 60}, inputs close, unit fraction
- Warm-up: 61 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `a0e237916f988aff184134bf6ecbab03dd9cd2b3e3ebe9b027e646b2150d130d`
- Version history:
  - 1 (2026-11-15): first version.

## ret_120d (version 1)

- Definition: close[t] / close[t-n] - 1
- Formula `ret`, parameters {'n': 120}, inputs close, unit fraction
- Warm-up: 121 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `d713f24981e4a872e1a960524af215cae64257c3db4e4b6b533c67aabfa4a000`
- Version history:
  - 1 (2026-11-15): first version.

## ret_252d (version 1)

- Definition: close[t] / close[t-n] - 1
- Formula `ret`, parameters {'n': 252}, inputs close, unit fraction
- Warm-up: 253 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `2c3e5525c03e30623d46b75b874712d13637e7e92bdd78adb7bc2026b23404f3`
- Version history:
  - 1 (2026-11-15): first version.

## vol_20d (version 1)

- Definition: sample standard deviation (ddof = 1) of the last n daily simple returns, not annualised
- Formula `vol`, parameters {'n': 20}, inputs close, unit fraction
- Warm-up: 21 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `826a4a5e3d43cc4e1c0898ae1d47229dabbf031f64098fcf3955f1972befb081`
- Version history:
  - 1 (2026-11-15): first version.

## vol_60d (version 1)

- Definition: sample standard deviation (ddof = 1) of the last n daily simple returns, not annualised
- Formula `vol`, parameters {'n': 60}, inputs close, unit fraction
- Warm-up: 61 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `f72bfd29aa0340217024eb9c68268f739f7e0f2b2f78054a659188480f9a3569`
- Version history:
  - 1 (2026-11-15): first version.

## atr_14d (version 1)

- Definition: Wilder ATR: first value is the mean of the first 14 true ranges, then ATR[t] = (ATR[t-1] * 13 + TR[t]) / 14; a gap restarts the chain; in price units as of t: multiplied by raw_close[t] / close[t] so a later split or bonus does not change it
- Formula `atr`, parameters {'n': 14}, inputs high, low, close, raw_close, unit price
- Warm-up: 15 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `0d1d9f3deddab2031633debf7f5c24c5c0153cdc213d1c190b800ca18640539b`
- Version history:
  - 1 (2026-11-15): first version. Before first use the ATR was rescaled by raw_close/close on day t, because a split or bonus taking effect after t had changed it (found by the look-ahead harness); no earlier hash was ever registered.

## atr_pct_14d (version 1)

- Definition: atr_14d / close[t]
- Formula `atr_pct`, parameters {'n': 14}, inputs high, low, close, unit fraction
- Warm-up: 15 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `ab63857df4dddfe70718468f400586118523da5044adb0dd16c3455f942c6679`
- Version history:
  - 1 (2026-11-15): first version.

## dist_sma_50d (version 1)

- Definition: close[t] / mean(close[t-n+1..t]) - 1
- Formula `dist_sma`, parameters {'n': 50}, inputs close, unit fraction
- Warm-up: 50 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `9f53d21c4da6e4084b1278189c57a4c70654cf8dedb3d7306bfe475a39d56891`
- Version history:
  - 1 (2026-11-15): first version.

## dist_sma_200d (version 1)

- Definition: close[t] / mean(close[t-n+1..t]) - 1
- Formula `dist_sma`, parameters {'n': 200}, inputs close, unit fraction
- Warm-up: 200 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `cdb12177d7fdc4eaa0a52724368b402a033f454fbcb48c6b5759403989281564`
- Version history:
  - 1 (2026-11-15): first version.

## traded_value_20d (version 1)

- Definition: mean over the last 20 sessions of raw close times raw volume
- Formula `traded_value`, parameters {'n': 20}, inputs raw_close, raw_volume, unit rupees
- Warm-up: 20 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `9ddcdb0b8a051e1d9d8fba1498a2210f765aa09ca893a010ca9ce4e83b6bd606`
- Version history:
  - 1 (2026-11-15): first version.

## ret_1d (version 1)

- Definition: close[t] / close[t-n] - 1
- Formula `ret`, parameters {'n': 1}, inputs close, unit fraction
- Warm-up: 2 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `f0e51db7bf5864f50bbb8c1e3bb1d07b170c7e1b8cd9ce6e81170a318196367f`
- Version history:
  - 1 (2026-11-16): first version.

## rsi_14d (version 1)

- Definition: Wilder RSI: the first value uses the mean of the first 14 gains and 14 losses, then avg[t] = (avg[t-1] * 13 + change[t]) / 14 for each; 100 - 100 / (1 + avg gain / avg loss); only rises give 100, no movement gives 50; a gap restarts the chain
- Formula `rsi`, parameters {'n': 14}, inputs close, unit index (0 to 100)
- Warm-up: 15 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `4f0b7c2beb0a2e423d08a0a88993d29759442c97838df8d3a8759cd14a1635b0`
- Version history:
  - 1 (2026-11-16): first version.

## dist_high_252d (version 1)

- Definition: close[t] / max(close[t-n+1..t]) - 1, never positive
- Formula `dist_high`, parameters {'n': 252}, inputs close, unit fraction
- Warm-up: 252 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `c513ffc989b43fb09e3ee4d2c81de55685fb4be947056530a4ca17275c393632`
- Version history:
  - 1 (2026-11-16): first version.

## dist_low_252d (version 1)

- Definition: close[t] / min(close[t-n+1..t]) - 1, never negative
- Formula `dist_low`, parameters {'n': 252}, inputs close, unit fraction
- Warm-up: 252 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `4a3e1d9bb60ecac9873d9a6357af80c3fdeb1dfad73ab93ffaf322522b433440`
- Version history:
  - 1 (2026-11-16): first version.

## volume_ratio_20_60d (version 1)

- Definition: mean raw volume of the last 20 sessions over the mean raw volume of the last 60; no value when the last 60 sessions traded nothing
- Formula `volume_ratio`, parameters {'short': 20, 'long': 60}, inputs raw_volume, unit ratio
- Warm-up: 60 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `f6691f9e85cd6b0e6a30f1465a9bea16158e71ba00341360cbf0f499d93c508a`
- Version history:
  - 1 (2026-11-16): first version.

## range_vol_20d (version 1)

- Definition: Parkinson range volatility: sqrt(mean(ln(high/low)^2 over the last 20 sessions) / (4 ln 2)), per day, not annualised; no value if any session has a non-positive low or a high below its low
- Formula `range_vol`, parameters {'n': 20}, inputs high, low, unit fraction
- Warm-up: 20 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `8ae74cbf1ff8d37784d15469479f96d63acc7a0b4b23707c0fed76db6f0620ab`
- Version history:
  - 1 (2026-11-16): first version.

## max_drawdown_60d (version 1)

- Definition: the deepest fall from a running peak among the last 60 closes: min over the window of close / running-high - 1, zero or negative
- Formula `max_drawdown`, parameters {'n': 60}, inputs close, unit fraction
- Warm-up: 60 bars (no value before the instrument has them)
- Availability: the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier
- manifest_sha256: `d44105bb2014925f5f38665b78e18910ccd9a7a053a50d7c4a7906b530135f13`
- Version history:
  - 1 (2026-11-16): first version.

## fund_revenue_growth (version 1)

- Definition: Sales growth (quarter, YoY): latest quarter ÷ same quarter a year earlier − 1
- Formula `fundamental_ratio`, parameters {'ratio': 'revenue_growth'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `7c8ca685164467db825f046311bd4a79ede91851f2a9e05d537862a3f312ac4b`
- Version history:
  - 1 (2026-11-15): first version.

## fund_profit_growth (version 1)

- Definition: Profit growth (quarter, YoY): latest quarter ÷ same quarter a year earlier − 1
- Formula `fundamental_ratio`, parameters {'ratio': 'profit_growth'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `75ce0ea42afb2e6238cbb6ad65459d949a847e8d2fdbe4c0f14da7718d7281a3`
- Version history:
  - 1 (2026-11-15): first version.

## fund_revenue_growth_ttm (version 1)

- Definition: Sales growth (12 months): last 12 months ÷ the 12 months before − 1
- Formula `fundamental_ratio`, parameters {'ratio': 'revenue_growth_ttm'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `cced443a92ad1cb6205ba029774566feda8aa46d0138cdd9007adae23bd0026c`
- Version history:
  - 1 (2026-11-15): first version.

## fund_profit_growth_ttm (version 1)

- Definition: Profit growth (12 months): last 12 months ÷ the 12 months before − 1
- Formula `fundamental_ratio`, parameters {'ratio': 'profit_growth_ttm'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `61a0ba9cd95758cf5ab0b35d6ac690dc926f510ddb121de36d33347f02af382b`
- Version history:
  - 1 (2026-11-15): first version.

## fund_net_margin (version 1)

- Definition: Net profit margin: net profit ÷ sales, last 12 months
- Formula `fundamental_ratio`, parameters {'ratio': 'net_margin'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `ffe81403544079a2b8113408bd0e3e5c85c2817b089134a8b8a1121cbd3af015`
- Version history:
  - 1 (2026-11-15): first version.

## fund_operating_margin (version 1)

- Definition: Operating margin: operating profit ÷ sales, last 12 months
- Formula `fundamental_ratio`, parameters {'ratio': 'operating_margin'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `5213a191eb9e54641e84d77520c481ad886d1c82b0a04451ef0bb2a1b6820c40`
- Version history:
  - 1 (2026-11-15): first version.

## fund_roe (version 1)

- Definition: Return on equity (ROE): profit to owners, last 12 months ÷ owners' equity
- Formula `fundamental_ratio`, parameters {'ratio': 'roe'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `48ef3a8a4680c5ba71f3639ba8997560f6fdc9311dba1cd2cce56785d1690f99`
- Version history:
  - 1 (2026-11-15): first version.

## fund_roa (version 1)

- Definition: Return on assets (ROA): profit, last 12 months ÷ total assets
- Formula `fundamental_ratio`, parameters {'ratio': 'roa'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `a7d856992cda8fef723fe39f4ed5ff892dc2506f672dd46a405ec4abacc66323`
- Version history:
  - 1 (2026-11-15): first version.

## fund_roce (version 1)

- Definition: Return on capital employed (ROCE): (profit before tax + interest) ÷ (total assets − current liabilities)
- Formula `fundamental_ratio`, parameters {'ratio': 'roce'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `74038b71fefff3822184277c41155b009ebe01e563f0b405e7a56c26855ad5d3`
- Version history:
  - 1 (2026-11-15): first version.

## fund_debt_to_equity (version 1)

- Definition: Debt to equity: borrowings ÷ owners' equity
- Formula `fundamental_ratio`, parameters {'ratio': 'debt_to_equity'}, inputs filings, unit x
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `ddfca4b6550c68bddfd9bda1ec5b16af1232111545ea66ef9293d69bc6a0d8ae`
- Version history:
  - 1 (2026-11-15): first version.

## fund_interest_coverage (version 1)

- Definition: Interest cover: (profit before tax + interest) ÷ interest, last 12 months
- Formula `fundamental_ratio`, parameters {'ratio': 'interest_coverage'}, inputs filings, unit x
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `0fd7644d4ed7e4143e5c79fa335d7c214e446bed2bea05a512af7ccfda2447cb`
- Version history:
  - 1 (2026-11-15): first version.

## fund_net_debt_to_ebitda (version 1)

- Definition: Net debt to operating profit: (borrowings − cash and investments) ÷ operating profit, last 12 months
- Formula `fundamental_ratio`, parameters {'ratio': 'net_debt_to_ebitda'}, inputs filings, unit x
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `d63fb03953fb82e199fb840b9e838bd1c9d4a5a2e975f19bfe3d2d27be4a7cea`
- Version history:
  - 1 (2026-11-15): first version.

## fund_current_ratio (version 1)

- Definition: Current ratio: current assets ÷ current liabilities
- Formula `fundamental_ratio`, parameters {'ratio': 'current_ratio'}, inputs filings, unit x
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `058ce88bb5f5e9b022f49fcd22dca8a2e03aa8b7ef7f6e19950ec3c87b5f7c98`
- Version history:
  - 1 (2026-11-15): first version.

## fund_asset_turnover (version 1)

- Definition: Asset turnover: sales, last 12 months ÷ total assets
- Formula `fundamental_ratio`, parameters {'ratio': 'asset_turnover'}, inputs filings, unit x
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `e5a1ffd22f9d46e8e9a8880423e02674d6cfdeb33bcf0907e1bd3acbf3257a03`
- Version history:
  - 1 (2026-11-15): first version.

## fund_cfo_to_profit (version 1)

- Definition: Cash from operations vs profit: cash from operations ÷ net profit, year to date
- Formula `fundamental_ratio`, parameters {'ratio': 'cfo_to_profit'}, inputs filings, unit x
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `b41f51d09c25760dbd9aa33d177725b68ce5d9c385da0399d0bc837c197c0932`
- Version history:
  - 1 (2026-11-15): first version.

## fund_fcf_margin (version 1)

- Definition: Free cash flow margin: free cash flow ÷ sales, year to date
- Formula `fundamental_ratio`, parameters {'ratio': 'fcf_margin'}, inputs filings, unit pct
- Warm-up: 0 bars (no value before the instrument has them)
- Availability: the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day
- manifest_sha256: `b2fa7870932e87045c82697a0550524dfdb1ce9d6bcb9bb177feebc3e0a91c9f`
- Version history:
  - 1 (2026-11-15): first version.
