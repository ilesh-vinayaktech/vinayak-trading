# UPL and TATACONSUM: the two rights-factor discrepancies explained (evidence only; recorded resolutions unchanged)

Both differences have one cause: the exchange F&O circular was issued BEFORE the final cum-date close and used the latest close available
when it was written. The formula is identical to ours (AF = (P - E) / P = TERP / P, full issue price). Only the reference close differs.

| | TATACONSUM (ex 2024-07-26) | UPL (ex 2024-11-26) |
|---|---|---|
| Exchange document | MSE circular MSE/TRD/15709/2024, dated 2024-07-25, created 09:50 IST (retrieved, stored, SHA-256 in `rights_evidence_manifest.json`) | NSE F&O circular 149/2024, dated 2024-11-22 (as reported; NOT retrieved: NSE archives time out to scripted access) |
| P used by the circular | 1231.25, labelled "last cum date" | implied 566.40 (solving TERP/P = 0.959510) |
| That P is the close of | 2024-07-24 (bhavcopy), the day before the last cum date | 2024-11-22 (bhavcopy), the circular's own date |
| Actual last cum-date close (our P) | 1223.60 on 2024-07-25 | 568.55 on 2024-11-25 |
| Circular factor | 0.987569 (= our formula at 1231.25: 0.98756909) | 0.959510 (= our formula at 566.40) |
| Our recorded factor | 0.987723 | 0.959243 (NSE's own indicative note FAOP65222 also used 568.55 and gave 0.959243) |

Reading: a cash-market price adjustment should use the close immediately before the ex-date, which is what the recorded factors use; the
circulars' figures are pre-close F&O operational numbers. This is an explanation, not a verification: both resolutions stay PROVISIONAL with
their conflict recorded as UNRESOLVED until the owner decides. Still missing for UPL: the NSE circular itself (FAOP number for 149/2024).
