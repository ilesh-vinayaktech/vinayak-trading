# Why some sessions have more than 200 constituents (Nifty 200, 2018-04-02 to 2026-11-06)

Generated check: `scripts/check_membership_counts.py` (data: `membership_session_counts.csv`, one row per NSE session, 2,133 sessions, counted from
`membership_intervals.csv` at the ACTUAL effective dates, one count per distinct constituent key). It exits non-zero if any session cannot be explained,
and if any placeholder overlaps its own real listing.

**Result: 1,126 sessions have exactly 200 constituents; 1,007 have 201, 202 or 204; every one of those 1,007 equals 200 plus entities NSE's own releases
add on top of the 200. 0 sessions are unexplained; 0 placeholders overlap their listing** (each placeholder is removed on the very day its listing is added,
so a spun-off company is one constituent, never two).

There are two genuine, NSE-documented reasons.

## 1. Tata Motors DVR is a 101st member of the Nifty 100 (551 + 227 sessions of 201)
Member 2018-04-02 to 2020-06-25 and 2023-09-29 to 2024-08-29. NSE's own month-end Nifty 200 constituent files list **201** names for all 26 months
2018-04 to 2020-05 and 200 from 2020-06-30 (checked in the database: 26 months of 201, none other); the releases' explicit Nifty 100 and Nifty 200 tables give the same
(48 of 48). Boundaries: removed 2020-06-26 (`pr_ind_prs10062020`), re-added 2023-09-29 (`pr_ind_prs17082023`), removed 2024-08-30 (`pr_ind_prs23082024_1`, capital reduction cancelling the DVR shares).
The month-end files stop at 2022-03, so 2023-09-29 to 2024-08-29 rests on the two releases only.

## 2. Demerged entities are added on top of the parent until NSE excludes them (the other 229 sessions)
NSE's methodology, in each release: the demerged entity "shall be included at zero price without divisor adjustment" under a dummy symbol on the special
pre-open day, while the parent stays. NSE later replaces the dummy with the real listing and excludes the new entity a few sessions afterwards. So the index
legitimately has 201+ names between those dates.

| Demerger | Added (dummy) | Release | Real listing from | Excluded from | Sessions above 200 | Counts |
|---|---|---|---|---|---|---|
| Reliance, Jio Financial | 2023-07-20 | `pr_ind_prs17072023` | 2023-08-21 | 2023-09-07 (`pr_ind_prs05092023`) | 34 | 201 |
| ITC, ITC Hotels | 2025-01-06 | `pr_ind_prs30122024` | 2025-01-29 | 2025-02-10 (`pr_ind_prs06022025_1`) | 26 | 201 |
| Siemens, Siemens Energy | 2025-04-07 | `pr_ind_prs02042025` | 2025-06-19 | 2025-06-27 (`pr_ind_prs25062025_2`) | 55 with ABFRL (2025-04-07 to 2025-06-26) | 201, 202 |
| ABFRL, Aditya Birla Lifestyle Brands | 2025-05-22 | `pr_ind_prs19052025` | 2025-06-23 | 2025-06-27 (`pr_ind_prs25062025_2`) | (in the 55 above) | 202 |
| Tata Motors, TML Commercial Vehicles | 2025-10-14 | `pr_ind_prs07102025` | 2025-11-12 | 2025-11-17 (`pr_ind_prs13112025`) | 22 | 201 |
| Hindustan Unilever, Kwality Wall's | 2025-12-05 | `pr_ind_prs28112025` | 2026-02-16 | 2026-02-24 (`pr_ind_prs20022026_1`) | 55 | 201 |
| Vedanta, four resulting companies | 2026-04-30 | `pr_ind_prs23042026` | 2026-06-15 | 2026-06-19 to 2026-06-24 (`pr_ind_prs17062026`, `19062026`, `22062026`) | 37 | 204, 202, 201 |

(The Siemens and ABFRL windows overlap from 2025-05-22 to 2025-06-26, so two demergers are extra at once: 202. Sessions: 34 + 26 + 55 + 22 + 55 + 37 = 229, plus 778 for the DVR = 1,007.)

## What the count does and does not claim
- The real listing date of a spun-off company, and the date NSE excluded it, come from a later release (D5): they are stored with their true effective date and
  the later announcement date (`announcement_date`), so a strict point-in-time query does not see them early.
- Nifty 200 membership AFTER the exclusion is 200 again on every session from 2020-06-26 except these windows.
- 2022-04 onwards has no month-end constituent lists; those months rest on the releases alone (Nifty 50, Next 50, Midcap 100 and the explicit sections of each release agree).
