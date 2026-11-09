# NESTLEIND post-apply check against the pre-migration baseline (read-only)

| mode | bars (baseline / now) | closes | factors | volumes | adjustment_version | owners |
|---|---|---|---|---|---|---|
| none (issuer via new) | 811 / 811 | True | True | True | True | [1589, 2653] |
| none (issuer via old) | 811 / 811 | True | True | True | True | [1589, 2653] |
| split (issuer via new) | 811 / 811 | True | True | True | True | [1589, 2653] |
| split (issuer via old) | 811 / 811 | True | True | True | True | [1589, 2653] |
| total_return (issuer via new) | 811 / 811 | True | True | True | True | [1589, 2653] |
| total_return (issuer via old) | 811 / 811 | True | True | True | True | [1589, 2653] |

- instrument-scoped reads are separate: new 704 bars, old 107 bars (expected 704 / 107): True

**Result: PASS**
