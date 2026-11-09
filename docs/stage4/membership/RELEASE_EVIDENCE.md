# Release evidence: membership revision 3

- Adopted commit: `a5fe86f` (baseline revision 2: `590466f`, recoverable with `git show 590466f:docs/stage4/membership/<file>`)
- Fresh-clone verification (2026-11-09): `git clone` of that commit, clean `uv sync --frozen`, `make check` exit 0 with 1238 passed and 100% line and branch coverage
- Artifacts in the clone are byte-identical to the working tree (sha256 below); counts: events 282, intervals 341, exceptions 13, cancellations 6, entity equivalences 2; coverage by month 19 CLEAN / 54 INCOMPLETE
- Independent monthly checkpoints: Nifty 50 73/73, Next 50 49/49, Midcap 100 18/18, derived and explicit N100 18/18, derived and explicit N200 18/18
- Still unresolved (not resolved by adoption): GSPL, JIOFIN pre-listing span, PEL x2 (instrument resolution); 9 non-tradable placeholders by design
- Point-in-time limit: listing-date handovers rest on later exclusion releases; contemporaneous NSE listing notices are not stored

## sha256
```
cb7ac0580a4a9021542ef4fadff8f53fb263f2ceb1aadcc011fb3b1bf49d7b56  docs/stage4/membership/membership_cancellations.csv
51cc8f27ad02b039eaf55990361e0eb516f473fa79e61080c2fc54ec2fe3290a  docs/stage4/membership/membership_entity_equivalence.csv
87cf749052523284e56a29208d5d1703a942467870bde57ed80249152562d4bc  docs/stage4/membership/membership_events.csv
88577da3dafa1d961cc7ae50fae657d6a21b9c4a79c8ba22d7b257e72be45210  docs/stage4/membership/membership_exceptions.csv
15515aa1183a4ec0e63f63f70ec3e73373a9f5083e7422b986dd8d1b18724bf6  docs/stage4/membership/membership_intervals.csv
3bbf3378f30f339dc1030214c49fa7a9096c44792183c9817b41e4240a49f7be  docs/stage4/membership/membership_coverage.json
cea5bcc491456d027be4c8d6a09fc307db47bffa79d049fbc1d014779aa5cd2e  docs/stage4/membership/membership_evidence_manifest.json
9f6546a37968eed6fdcf84f583a13f0a10c8a7f1efbcb074b979d159a6d166a5  docs/stage4/membership/membership_reconciliation.json
```
