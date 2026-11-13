# Benchmark Release 1.5 - change report against 1.4

Covers all 49 benchmark series (1.4 covered the first four). Same findings and decisions as 1.4.

- The 45 added indices (broad, sector, thematic; total-return gross, from 2015-01-01) are judged on their own validation (technical checks and factsheet reconciliation) and the findings that apply to every series. They are NOT part of the cross-series alignment/discontinuity audit (`--extra-ids`): that audit compares series that should move together, which sector indices need not (run on all 49 it flags 41 sector-specific moves as uncorroborated and would wrongly block the original four).
- 46 series are BENCHMARK_GATE_ELIGIBLE (all Nifty 200 / Nifty 50 gross and price series from 1.4 plus 43 indices).
- Not eligible: Nifty 50 net (technical validation, U06, U08); Nifty India Defence (5-year CAGR differs from the factsheet by 0.027 pp, tolerance 0.02) and Nifty Capital Markets (5-year CAGR differs by 0.307 pp): "factsheet reconciliation did not pass". Both stay DATA_INGESTED until reviewed.
