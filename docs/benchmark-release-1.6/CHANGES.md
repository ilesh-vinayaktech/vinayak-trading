# Benchmark Release 1.6 - change report against 1.5

- Nifty Capital Markets now reconciles to its factsheet (5-year CAGR diff -0.0175 pp): the 5-year base is the last session on or before end - 5 years (1.5 used end - 5 years + 1 day, a day out for this sheet; it gives the same base on every other index's sheet). `niftyindices_factsheet.build_checks` follows the corrected rule.
- Nifty India Defence: owner-accepted 5-year tolerance 0.03 pp (diff -0.0268 pp; the day-count convention alone moves a 47% CAGR by about 0.04 pp; the other four checks agree to 0.004 pp). Recorded in `config/factsheet_checks/nifty_india_defence_2026-10-30.json`.
- Result: 48 series BENCHMARK_GATE_ELIGIBLE; Nifty 50 net is not (technical validation, U06, U08).
