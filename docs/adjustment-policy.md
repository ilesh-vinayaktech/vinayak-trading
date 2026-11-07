# Corporate-action adjustment policy

Raw bars are never edited. Adjustment is applied at read time (`data/reader.py`).

## Three different things (never interchangeable)
| Concept | What it is | Where |
|---|---|---|
| COST_ALLOCATION | Tax cost-of-acquisition split between resulting companies | evidence only; **not** a price factor by itself |
| PRICE_ADJUSTMENT | Factor applied to pre-ex-date parent prices to remove an artificial gap | `Adjustment` (price-only) |
| TOTAL_RETURN_ENTITLEMENT | Value of child shares / rights / dividends a holder receives | portfolio accounting (backtest ledger) |

## Demerger price adjustment: evidence hierarchy (owner decision, 2026-11-07)
Factor = exchange-adjusted parent base price / previous cum-entitlement close. Apply to historical
parent OHLC before the ex-date; raw prices stay untouched.

| Priority | Evidence / method | Resolution method | Treatment |
|---|---|---|---|
| 1 | Exchange special pre-open price discovery (only for securities it applies to) | `exchange_adjusted_price` | preferred; may be `verified` with source |
| 2 | Official exchange-published adjustment factor | `exchange_adjusted_price` / `direct` | use if available and applicable |
| 3 | Official scheme and company disclosures | `direct` / `demerger` with documented method | `verified` only with the derivation written in `note` |
| 4 | Tax cost allocation | `cost_allocation` | recorded separately; not a default price factor |
| 5 | Child's first traded price | `demerger` | cross-check only |
| 6 | Peer-adjusted `gap` estimate | `gap` | **provisional, research only; never verifiable; never a fallback for a verified factor** |

Events where no defensible factor can be established stay unresolved. A price-adjusted parent
series is price-continuous, not wealth-continuous: the child shares received are a separate
entitlement (see TOTAL_RETURN_ENTITLEMENT, not yet modelled).

## Resolution statuses
`provisional` (estimate; research only) · `verified` (factor + source + verifier) ·
`no_adjustment_verified` (reviewed, none needed, source cited) · `ignored_with_reason` · `rejected`.
`gap` estimates are diagnostic and can never be verified.

## Reader modes
* **strict**: verified factors only; any unpriced or provisional action affecting the range => refuse.
  Only strict results may support strategy validation / promotion.
* **research**: also applies provisional factors, but always lists them (`History.provisional`) and
  unpriced items (`History.unapplied`) separately; every read carries `adjustment_version`.

## <a name="buy-backs"></a>Buy-backs (owner decision, 2026-11-07)
A buy-back (tender offer, open-market or exchange-mechanism) does not change any holder's share
count and creates no mechanical discontinuity, so **no historical OHLC adjustment is made**. The
event record is preserved (shares outstanding, valuation, fundamentals still need it).
Recorded as `no_adjustment_verified`, method `ignore` (factor 1.0), source_type `methodology_policy`,
source_url `docs/adjustment-policy.md#buy-backs`.

## Rights issues
Factor = TERP / cum price from the **offer document's** ratio and issue price. No estimates:
rights stay unresolved (blocking strict) until verified from the filing.

## Dividends
`price_return` excludes dividends; `total_return` folds in cash dividends (factor = 1 - D / prev close).

## Backtest modes (what each run proves)
| | research | strict |
|---|---|---|
| Corporate-action data | verified **and** provisional estimates | verified only |
| Instruments with unresolved / provisional actions | included; events listed in the run record | **blocked** (excluded, reason recorded) |
| Persisted on every run | reader mode, per-instrument `adjustment_version`, provisional events with factors, unapplied events (separate), blocked instruments, unmodelled events, result hash | same |
| Can support promotion beyond research | **never** | only if also: no provisional/unapplied events, accounting complete, non-placeholder costs, validation protocol passed |

Execution and accounting always use RAW prices; adjusted prices are for signals only.
Not yet modelled: child shares / rights entitlements in portfolio accounting, versioned cost
schedule, financial ledger, validation protocol. These must exist before any strategy promotion.
