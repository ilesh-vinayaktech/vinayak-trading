# Demergers still on `gap` estimates: proposal (read-only; nothing applied)

## A. Exchange-discovered base price (6): proposed `exchange_adjusted_price`, factor = ex-date open / previous close

| symbol | ex-date | prev close | base (ex-date open) | proposed factor | current gap factor | difference | entitlement |
|---|---|---|---|---|---|---|---|
| RELIANCE | 2023-07-20 | 2841.85 | 2580.00 | 0.9078 | 0.9198 | -0.0120 | 1 Jio Financial Services share per Reliance share |
| ITC | 2025-01-06 | 481.60 | 455.60 | 0.9460 | 0.9449 | +0.0011 | 1 ITC Hotels share per 10 ITC shares |
| SIEMENS | 2025-04-07 | 4928.15 | 2450.00 | 0.4971 | 0.5905 | -0.0934 | 1 Siemens Energy India share per Siemens share (record date 2025-04-07, Siemens' own NSE filing) |
| TMPV | 2025-10-14 | 660.75 | 400.00 | 0.6053 | 0.6025 | +0.0028 | 1 TMLCV share per Tata Motors share |
| HINDUNILVR | 2025-12-05 | 2462.20 | 2422.00 | 0.9836 | 0.9468 | +0.0369 | 1 Kwality Wall's (India) share per HUL share |
| VEDL | 2026-04-30 | 773.60 | 289.50 | 0.3742 | 0.3548 | +0.0194 | 1 share each of four demerged Vedanta companies per Vedanta share (record date 2026-05-01) |

Evidence per row (stored NSE bhavcopy file checksum and press reports) is in `config/proposed/demerger_resolutions.json`. The open equals the discovered price reported by the press in every case. This is a proposal: verification (a person confirming against the NSE circular) is separate.

## B. No special session (4): no exchange base exists; candidates only

| symbol | ex-date | prev close | entitlement | gap (current) | child | child first session | days after ex | factor if child's first close |
|---|---|---|---|---|---|---|---|---|
| ABB | 2019-12-20 | 1476.00 | 1 ABB Power Products share per 5 ABB India shares | 0.8544 | POWERINDIA | 2020-03-30 | 101 | 0.9033 |
| GMRAIRPORT | 2022-01-11 | 48.45 | 1 GPUIL share (FV 5) per 10 GIL shares (FV 1) | 0.9277 | GMRP&UI | 2022-03-23 | 71 | 0.9059 |
| MOTHERSON | 2022-01-14 | 234.80 | 1 MSWIL share per MSSL share (reports) | 0.7909 | MSUMI | 2022-03-28 | 73 | 0.7362 |
| NMDC | 2022-10-27 | 130.75 | 1 NMDC Steel share per NMDC share | 0.7914 | NSLNISP | 2023-02-20 | 116 | 0.7572 |

The child's first close is lagged by weeks to months (and ABB's by the March 2020 crash), so it is a poor stand-in for value at the ex-date. Company tax cost apportionments (e.g. NMDC 42.71% / NMDC Steel 57.29%, GMR 7.29% to GPUIL) are book-value based and not comparable with market value. A person must choose the convention or keep these as provisional gap estimates.
