# Verification record: Nifty 200 membership, revision 4

- **Owner decision date:** 2026-11-15
- **Verified by:** Ilesh Patel (owner)
- **Index / coverage:** NIFTY200, 2018-04-02 to 2026-11-07
- **Membership source:** revision 4 reconstruction (`membership_intervals.csv`, `membership_events.csv`), loaded by `scripts/load_membership.py` (586 events, one coverage), PROVISIONAL until this record.
- **Decisions:** D1 TATAMTRDVR approved. D2 BHARATFIN / HEXAWARE approved. D3 GSPL / PEL approved, identity and re-mapping only, price bars held until their corporate actions are loaded and validated. D4 placeholders accepted, they remain members through `constituent_key`. D5 retrospective handovers accepted, actual effective dates and announcement dates kept apart. Daily constituent-count validation accepted: 2,133 sessions, 1,126 at 200, 1,007 at 201/202/204, all explained by NSE releases (`membership_counts.md`), 0 unexplained, 0 placeholder/listing overlaps.
- **Point-in-time semantics:** announcement date (`members_on`, `constituents_on` default). **Historical semantics:** actual effective date (`historical=True`).
- **Constituent identity:** `constituent_key` (`i:<instrument_id>`, `p:<SYMBOL>`, `s:<SYMBOL>`).
- **Price eligibility is independent of this verification.** VERIFIED membership does not mean every constituent has usable historical prices. A strict-mode experiment must still enforce price availability, corporate-action readiness and instrument identity on its own.
- **Explicit exclusions:** history before 2018-04-02; prices before 2019-10 (older NSE price files not loaded); price bars of GSPL and PEL (held); BHARATFIN has no prices; month-end constituent lists end at 2022-03 so later months rest on the releases alone.
