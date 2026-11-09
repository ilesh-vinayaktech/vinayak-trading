# NESTLEIND membership handover (2026-11-09)

Rests on the VERIFIED conversion instruction (`security_conversion`, 2653 to 1589, effective 2024-01-05, commit d17a1e9). A bare
SAME_ISSUER_ISIN_CHANGE relationship does not trigger it; the reconstruction reads `load_conversions` (VERIFIED rows only).

Code: `hand_over_isin_changes` / `hand_over_spans` in `src/algo/data/membership_reconstruction.py` (pure, tested), wired into
`scripts/reconstruct_nifty200_membership.py`. Output change: only `membership_intervals.csv`; events, reconciliation, coverage, exceptions are byte-identical.

| Before (revision 3) | After |
|---|---|
| `i:1589` member 2020-10-01 to open (WINDOW_START) | `i:2653` 2020-10-01 to 2024-01-05 exclusive (WINDOW_START); `i:1589` from 2024-01-05 to open (ISIN_CHANGE_HANDOVER) |

Review checks, on the real database (read-only):
| Check | Result |
|---|---|
| Old instrument's membership ends on the correct date | 2653 last member day 2024-01-04 (end exclusive 2024-01-05); its last bar is 2024-01-04 |
| New instrument becomes eligible on the correct date | 1589 first member day 2024-01-05 = its first bar |
| Never both members because of the ISIN transition | exactly one member on every day (unit test over 2020-10-01..2024-03-01; real: 805 trading days, 0 mismatches between the member and the instrument that has a bar that day) |
| Historical signals keep issuer continuity | unchanged and already tested: signals are issuer-scoped (`issuer_load`); membership only decides the tradable instrument |
| Orders, fills, holdings instrument-specific | unchanged (instrument-scoped); a membership name now always has bars of its own on every member day |
| Backtest spanning the transition converts holdings exactly once | `nestleind_conversion_instruction_persisted.md`: 39 old become 390 new on 2024-01-05, once; `tests/integration/test_conversions.py` |

Not changed, stated plainly: the 3 unmapped NESTLEIND component release rows, `listed_on` of 1589 (2023-08-01), and the older universe pipeline
(`universe_build.py`, DB events table is empty). Membership events are not rewritten: the issuer is a member continuously, so there is no
ADD/REMOVE at the handover; the interval boundary is a handover, not a membership change.
