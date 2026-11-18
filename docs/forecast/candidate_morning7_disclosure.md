# Candidate morning7: disclosure and correction (2026-11-18, added after the freeze)

The frozen specification (`candidate_morning7_spec.md`, hash in `candidate_morning7_freeze.json`) says the candidate "was chosen on development-period results (to 2024-12-31)" and that
"nothing from 2025-01-01 on ... was used to choose this candidate's design". **That is not accurate.** The frozen file is not edited (its hash is the record); this addendum corrects it.

## What happened
The ablation that led to the 7-feature set (all 18 features, without FII, without gold, US overnight plus price only, without US overnight) and the three-period comparison were run on **all 1,678 days
from 2020-02-11 to 2026-11-16**, which include the accessed 2025-2026 period. The 7-feature set was therefore chosen with results that included that period in view. The later diagnosis, calibration and
volatility work used development data only, and says so.

## How much it matters: a development-only replication
The same comparison, with the models fitted and scored only on days up to 2024-12-31 (1,212 days, 2020-02-12 to 2024-12-31), run after the freeze:

| Inputs | Accuracy | Brier skill vs usual tendency |
|---|---|---|
| All 18 features | 60.9% | +0.0428 |
| Without FII positioning | 61.1% | +0.0427 |
| Without gold | 60.7% | +0.0459 |
| **US overnight + price returns (the 7)** | **64.0%** | **+0.0607** |
| Without US overnight | 56.4% | -0.0093 |

Paired Brier gap, 18 features minus 7 (positive favours the 7): +0.0044, 95% +0.0005 to +0.0093 (blocks of 20 days). By period: 2020-21 +0.0050 (-0.0036 to +0.0162), 2022-23 +0.0029 (-0.0013 to +0.0074),
2024 +0.0062 (-0.0006 to +0.0145). The conclusions are the same as on the full sample (US overnight carries the forecast; FII and gold add nothing; the 7-feature set is ahead), and the pooled interval
sits just above zero, but no single period's interval excludes zero.

## Effect on the rules
- Nothing in the frozen specification changes. The 2025-onward period was never confirmation data for this candidate and still is not.
- This reinforces the rule that only forward predictions made after the freeze can confirm it. The candidate is a research candidate whose choice was informed by accessed data, tested on genuinely new observations.
- Any future candidate must say in its specification which data its design was chosen on, and use development-only runs (cutoff `algo.factory.study.WINDOW[1]`) for choosing.

## Known limitation found while building the volatility forecast (2026-11-18, not fixed: the frozen code is unchanged)
`global_markets.last_session_return` returns the move of the last US session **stored** before the forecast session. If a US close is missing from `global_daily` (not loaded yet, or a failed ingest), the frozen direction forecasts
(`morning` and `morning7`) silently use the previous stored session's move as "the overnight move" instead of making no forecast. A US holiday is a legitimate case of the same fallback. The new volatility forecast does not have this
weakness (it requires the US session that has just closed and makes no forecast otherwise). Effect on the direction experiment: both models share the behaviour, so the paired comparison is not biased by it, but an
affected day carries a stale input. The morning job loads the US closes first, so it should be rare; the evaluation report cannot currently show how many days it happened. Not changed here because the implementation is frozen.
