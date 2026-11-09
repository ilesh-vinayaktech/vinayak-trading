# NESTLEIND conversion instruction: persisted verification

- config `config/security_conversions/nestleind.json`: INE239A01016 to INE239A01024, 10:1, effective 2024-01-05, VERIFIED
- config sha256 `2948f44d274dce32791cc64ae141df34be14c855b62aa479a51f2ca0ebfcd028`
- read-only on the persisted instruction

| check | result |
|---|---|
| schema: ratio numerator positive | PASS |
| schema: ratio denominator positive | PASS |
| schema: evidence must be a non-empty array | PASS |
| schema: a security cannot convert into itself | PASS |
| schema: last source session before the effective date | PASS |
| schema: status limited to PROVISIONAL / VERIFIED / REJECTED | PASS |
| schema: unique per (source, target, effective date) | PASS |
| schema: absorbed date and kind together or neither | PASS |
| schema: foreign keys to both instruments and to the relationship | PASS |
| exactly one instruction is recorded | PASS |
| source and target resolved from the ISINs | PASS |
| effective date and last source session | PASS |
| ratio 10:1 (target shares per source share) | PASS |
| absorbed action is the same-date split | PASS |
| evidence references equal the config (3 NSE circulars) | PASS |
| status VERIFIED, review decision recorded | PASS |
| linked to the existing SAME_ISSUER_ISIN_CHANGE relationship | PASS |
| the loader returns it (reference, absorbed split, verified) | PASS |
| engine: exactly one conversion applied | PASS |
| engine: converted on the new ISIN's first session = the effective date | PASS |
| engine: quantity x10, cost basis unchanged | PASS |
| engine: the only trade is the one purchase of the old ISIN | PASS |
| engine: no realised P&L and no fees | PASS |
| engine: ledger reconciles, accounting complete, nothing unmodelled | PASS |
| engine: the converted position is held at the new quantity to the end | PASS |

- engine run: 1 trade(s), 1 conversion(s), final positions {1589: Decimal('390')}, unmodelled []
- 39 old shares -> 390 new shares, cost basis 978812.25; equity 10078727.35 (2024-01-04) -> 10061083.75 (2024-01-05), change -17643.60 (the market move of one session)

**Result: PASS**
