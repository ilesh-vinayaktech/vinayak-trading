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
