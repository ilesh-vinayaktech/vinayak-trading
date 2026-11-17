# Bootstrap pilot (holdout policy v3, section 2 / step 5), 2026-11-17

Implementation: `src/algo/backtest/validation/mc_bootstrap.py` (numpy 2.2.6, PCG64), tests `tests/unit/backtest/validation/test_mc_bootstrap.py`.
Measured on the dev machine (x86_64, Python 3.12.3, 15 GB RAM shared with a study worker and Postgres): n = 460, D = 10,000, blocks one at a time.

| Measure | Result |
|---|---|
| 100,000 draws (10 blocks) | 2.1 s, so about 48,000 draws/s on one core |
| Peak resident set (`ru_maxrss`), whole process | 198 MB |
| One candidate at B = 1,000,000 (extrapolated, not yet measured in full) | about 21 s |
| Batch 1 production (4 eligible candidates) | about 1.5 minutes |

**Calibration cost at this speed (extrapolated, one core):** 7 series x 310,000 datasets x 20,000 draws = 4.3 x 10^10 draws, about 10.5 days; the drift diagnostic adds 1.9 x 10^10 draws, about 4.5 days. About 15 core-days, so about 5 days on 3 workers (memory allows about 3). The D8 fallback (230,000 datasets) saves only 26%. The speed must improve before the calibration is practical (for example a float32 or compiled kernel, or fewer draws per dataset, each a change to the frozen method and so a dated amendment) or the owner accepts a multi-day batch job. The full-candidate peak-RSS measurement (all 100 blocks, with data loading) is still to be done on the final code.

## Update: faster kernel (same day)
The index build now packs each restart as (position << 15 | index) so a single running maximum replaces the gather and the modulo. Output is bit-identical (the worked examples, golden values and the 100,000-draw count k = 54,578 are unchanged). Single-core speed rose only from 2.1 s to 1.87 s per 100,000 draws (about 53,000 draws/s): the random-number generation (about 0.06 s of each 0.19 s block) is the floor, and it cannot change without changing the frozen stream.
**The real gain is parallelism: the machine has 16 cores and one block needs about 200 MB.** Calibration is independent per dataset and per chunk (section 2.2 keys), so with 12 worker processes (about 2.4 GB) the 6.2 x 10^10 draws take about 1.1 x 10^6 core-seconds / 12, about 1 day. The calibration runner must therefore be multi-process; this changes no statistic and needs no amendment.

## Calibration runner (built 2026-11-17)
`algo/backtest/validation/mc_calibration.py` and `scripts/holdout_calibration.py` implement section 2.2: the seven series, the drift diagnostic, the joint index, the keyed randomness (chunk of 1,000 datasets from `(series, chunk, 0)`, dataset bootstrap seed `(series, chunk, 1, j)`), chunked resumable storage and a process pool, and the exact binomial rules, which reproduce the policy's figures (boundaries 574, 567, 557, 433; tails 0.6836%, 0.7691%, 1.5097%, 1.6800%). 14 unit tests.
**Measured on one core: 0.34 s per dataset at B = 20,000, so about 5.7 minutes per chunk of 1,000, and about 292 core-hours for the 7 decision series (310,000 datasets each) plus the 3 drift checks: about 24 hours on 12 of the 16 cores.** The power and full-policy pass runs (21 cells at 10,000 datasets each) add about 20 core-hours. Start with `scripts/holdout_calibration.py run --out DIR`; it has NOT been run yet. The full-candidate peak-RSS measurement of section 2 (all 100 blocks at B = 1,000,000 with data loading) is still to do with the final production code.

## Update: row-sliced kernel (2026-11-17, later)
Each draw block is still generated whole (the stream is untouched) but its indices, gather and Sharpe are computed in slices of 256 rows that fit the cache. Output is identical (k = 54,578 at every slice size from 1 row to 10,000; golden values unchanged); speed rose from 1.87 s to 0.71 s per 100,000 draws on an idle machine. Calibration estimate: about 110 core-hours, about 7.5 hours on 15 of the 16 cores (the first run was started at 12 workers on the slower kernel and stopped before any chunk finished).
