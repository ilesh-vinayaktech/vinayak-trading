# Listing-notice evidence for ENRIN, ABLBL, VAML, VEDPOWER, VOGL, VISL

**Evidence only.** No instrument, alias, membership or coverage write was made, and no `known_at` in Revision 3 was changed.
Originals are in `originals/`; hashes, URLs, PDF creation times and page references are in `manifest.json`.

## Summary

| Security | Listing date stated by a retrieved NSE notice | ISIN in a retrieved notice | Matches master ISIN | Matches Revision 3 handover date | Status |
|---|---|---|---|---|---|
| VAML | 2026-06-15 (press release, p.2) | INE1CDF01017 | yes | yes (2026-06-15) | **established** |
| VOGL | 2026-06-15 (p.2) | INE704J01044 | yes | yes | **established** |
| VISL | 2026-06-15 (p.3) | INE1CLE01013 | yes | yes | **established** |
| VEDPOWER | 2026-06-15 (p.3) | INE694L01019 | yes | yes | **established** |
| ENRIN | not stated in a notice I could retrieve | none | master has INE1NPP01017 (unverified here) | consistent, not primary-verified | **partial** |
| ABLBL | not stated in a notice I could retrieve | none | master has INE14LE01019 (unverified here) | consistent, not primary-verified | **partial** |

## What each retrieved document establishes

- **`PR_LIST_11062026.pdf`** (NSE press release, Mumbai, 11 June 2026; PDF created 2026-06-11 19:41 IST). Press Releases 3 to 6 list the four Vedanta
  companies "listed and admitted to dealings on the Exchange w.e.f. June 15, 2026", series `BE*` (trade-for-trade, later `EQ`), with ISINs.
  It states a **listing date** and an **ISIN**. It does **not** state a separate trading-commencement time.
- **`CML74701`, `CML74702`, `CML74703`, `CML74704`** (NSE circulars dated 15 June 2026, created 11:48 to 14:44 IST): move VISL, VEDPOWER, VAML and
  VOGL from series BE to EQ w.e.f. 2026-06-30, and cite the individual listing circulars of 2026-06-11 (NSE/CML/74664, 74668, 74659, 74666). They confirm
  the symbol and the security existed in series BE on 2026-06-15; they do **not** state a listing date.
- **`CML68621`** (dated **19 June 2025**, created 12:45 IST): ENRIN BE to EQ w.e.f. 2025-07-03, "further to Exchange Circular NSE/CML/68579 dated
  June 17, 2025". **`CML68683`** (dated **23 June 2025**, created 12:55 IST): ABLBL BE to EQ w.e.f. 2025-07-07, "further to NSE/CML/68628 dated
  June 19, 2025". Neither states a listing date or an ISIN; both were created on the listing day itself, after the open.

## Discrepancies and gaps against Revision 3

1. **ENRIN and ABLBL: the primary listing circulars are missing.** NSE/CML/68579 (2025-06-17) and NSE/CML/68628 (2025-06-19) could not be fetched:
   the archive returned a web page instead of a PDF, and further attempts timed out. I stopped there and did not try to get around the site's
   protections. The listing dates in Revision 3 (2025-06-19 and 2025-06-23) are consistent with the circulars that cite them and with secondary
   reports, but they are not yet backed by a primary notice that states them. **To close this:** download the two circulars (and, for completeness,
   74659, 74664, 74666, 74668) from the NSE circulars page, put them in `originals/`, and they can be hashed and added.
2. **Vedanta `known_at` can move earlier.** Revision 3 keeps the later exclusion releases (2026-06-17, 19, 22) as the announcement date of each handover.
   The listing date itself was publicly stated on **2026-06-11 (19:41 IST)**, four days before listing. This is a *candidate* correction for the
   knowledge date of the listing event only; it is not applied. Whether the index handover itself was knowable then depends on the index methodology
   notice, which is a separate document.
3. **Two timelines, kept apart.** `effective_date` (2026-06-15, 2025-06-19, 2025-06-23) is when the listing took effect. `known_at` is when it became
   public. For ENRIN and ABLBL the retrieved circulars were created on the listing day after the open, so they prove nothing about earlier knowledge;
   the cited circulars of 17 and 19 June 2025 might, once read. Any "conservative cutoff" a reader applies (for example the start of the ex-date)
   must be labelled as that policy, not recorded as an announcement date.
4. **Allotment is not listing.** None of the dates above come from an allotment; the Revision 3 handovers use listing dates only.
5. **ISINs.** The four Vedanta ISINs in the master equal the NSE press release exactly. ENRIN (INE1NPP01017) and ABLBL (INE14LE01019) come from the
   master and secondary reports only.

## What this does not change

A same-issuer or placeholder relationship does not move membership to a tradable instrument before the evidenced handover date. Instrument 1589 is not
migrated. The membership interval correction for the ISIN change remains a separate requirement.
