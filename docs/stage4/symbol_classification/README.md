# Unmapped membership symbols: read-only classification (2026-11-08)

Produced by `scripts/classify_unmapped_symbols.py`. Nothing was written to the instrument master,
aliases or membership tables. Every row is UNREVIEWED: only person-reviewed mappings may enter the
authoritative identity tables.

Files: `symbol_classification.csv` (evidence + proposed category, all 839 symbols), `mapping_candidates.csv`
(proposals needing review), `unresolved.csv`, `mapped_identity_check.csv` (the rows that already mapped),
`summary.json` (counts by scope, category, confidence).

## The headline
Of 839 symbols (827 unmapped + 12 placeholders), only **11 are in the Nifty 50 / Next 50 / 100 / 200 /
Midcap 100 family** (151 release rows). The other 828 come only from other indices (SME Emerge,
Smallcap 250, MidSmallcap 400, Total Market, thematic) and cannot affect a Nifty 200 strategy.
Those 590 "never in any exchange file" symbols are SME-segment names that the EQ bhavcopy does not carry.

## The 11 family symbols
| Symbol | Category | Needs |
|---|---|---|
| DHANI, MINDTREE | DELISTED_WITH_PRICES | the release rows carry NO effective date; take it from the document |
| NESTLEIND | REPLACED_ISIN | ISIN INE239A01016 -> INE239A01024; verified 2024-01-05 face-value split corroborates; confirm date |
| DUMMYABFRL, DUMMYSIEMS | PLACEHOLDER | keep out of the instrument master; model the demerger placeholder separately |
| PEL, GSPL, ABIRLANUVO, DALMIABHA | UNRESOLVED (name+timing candidate only) | successor / merger consideration unestablished |
| HEXAWARE, BHARATFIN | DELISTED_NO_PRICES | prices exist in the archive (and raw lake); no successor evidence |

## Identity check on rows that DID map (313 symbol-instrument pairs)
209 ISIN agrees; 27 same issuer with a changed ISIN (face-value changes, renames); 18 instruments with no
ISIN recorded (inferred delisted); 59 no ISIN evidence; **0 mapped to a different issuer**.
ISIN equality is strong evidence, not proof: a reviewer still signs off.
