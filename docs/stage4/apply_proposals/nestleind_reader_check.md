# NESTLEIND reader check (read-only, in memory; instrument 1589 is NOT migrated)

- bars: 811 total = 107 before 2024-01-05 (old ISIN) + 704 from 2024-01-05 (new ISIN)
- corporate actions: 53 total = 43 before + 10 from the change
- release rows: 0 total, 0 dated before the change, 0 undated

- stitched bars 811 (= 811), owners old/new 107/704; actions 53 (= 53 distinct)

| mode | bars | closes equal | factors equal | volumes equal | adjustment_version equal |
|---|---|---|---|---|---|
| none | 811 | True | True | True | True |
| split | 811 | True | True | True | True |
| total_return | 811 | True | True | True | True |

- prefix invariance (as of the afternoon before 2024-01-05): True

**Result: PASS**
