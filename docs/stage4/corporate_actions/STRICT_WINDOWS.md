# Strict-mode windows for the ten demergers (engine change a39b0f3)

In strict mode a name is withheld on a decision day only while the strategy's requested window still reaches back across an unresolved
(or merely provisional) action that is already known. The momentum strategy requests `LOOKBACK_DAYS = 440` calendar days, so for it
the withheld span runs from the ex-date until 440 calendar days later. Outside that span the action no longer blocks the name.

| symbol | ex-date | resolution | withheld from | eligible again from (momentum, 440 days) |
|---|---|---|---|---|
| ABB | 2019-12-20 | provisional gap estimate (kept; no exchange base) | 2019-12-20 | 2021-03-05 |
| GMRAIRPORT | 2022-01-11 | provisional gap estimate (kept; no exchange base) | 2022-01-11 | 2023-03-28 |
| MOTHERSON | 2022-01-14 | provisional gap estimate (kept; no exchange base) | 2022-01-14 | 2023-03-31 |
| NMDC | 2022-10-27 | provisional gap estimate (kept; no exchange base) | 2022-10-27 | 2024-01-11 |
| RELIANCE | 2023-07-20 | provisional exchange-derived (once recorded) | 2023-07-20 | 2024-10-03 |
| ITC | 2025-01-06 | provisional exchange-derived (once recorded) | 2025-01-06 | 2026-03-23 |
| SIEMENS | 2025-04-07 | provisional exchange-derived (once recorded) | 2025-04-07 | 2026-06-22 |
| TMPV | 2025-10-14 | provisional exchange-derived (once recorded) | 2025-10-14 | 2026-12-29 |
| HINDUNILVR | 2025-12-05 | provisional exchange-derived (once recorded) | 2025-12-05 | 2027-02-19 |
| VEDL | 2026-04-30 | provisional exchange-derived (once recorded) | 2026-04-30 | 2027-07-15 |

Notes:
- A provisional exchange-derived factor is still not VERIFIED, so strict mode withholds those six too until the circulars are obtained and verified. Research mode applies the factor and lists it as provisional.
- Conservative by design, and by about 75 calendar days: the longest feature needs 252 sessions (about 365 calendar days), but the strategy requests 440 calendar days and the rule follows the request. Declaring lookbacks in sessions instead of calendar days would shorten the withheld span; that is a strategy-interface change and was not made.
- A withheld name is neither bought nor sold that day. A position held across an unresolved action is flagged unmodelled, so such a run is never complete.
- Not being a member on the ex-date does not make the action irrelevant: a later membership period inside the span is withheld exactly the same way.
