# Holdout policy v3, step 0: procedure-provenance audit (interim, 2026-11-16)

Status: **PARTIAL, NOT SIGNED** (discovery re-run done and matching; availability list gaps and the Batch 1 cutoff remain). Times UTC (git shows IST, +05:30). Built from the database and git on 2026-11-16 after section 9 was signed.

## Established (from the database and git)
- **Candidate generation.** 16 `ALPHA_*` definitions, all created 04:54:20 by `generate_strategies`, insert-only, hashed. They are exactly the 16 expressible batch 1 hypotheses (CANDIDATE) from alpha discovery batch 1 (ran 04:30:32, `dataset_sha256 f8127df9ed`, 108 tests). The other 6 batch 1 candidates (`atr_pct_14d`, `rsi_14d`, `fund_operating_margin`) were refused by the generator, each with a recorded reason.
- **Reproduction of generation (done).** Running the current `generate.candidates` + `definition_for` over the stored hypotheses (batches 1 and 2) yields the same 16 strategy ids; the one hash checked (`ALPHA_DIST_SMA_50D_H1`) equals the stored `definition_sha256`. Batch 2 (04:56, same dataset) added no new strategy.
- **Discovery code at run time.** Batch 1 ran at 04:30 UTC = commit `a693cdf` (10:00 IST, "one feature at a time"). Features: formulas frozen in `docs/vti-phase1-spec.md` (committed 2026-11-14, `9d35d11`/`90b9fd6`); price features `330b29f`/`bb914db`, 2026-11-15 to 16 00:42 IST.
- **Source of design parameters.** Horizons: `scripts/discover_alpha.py` default `1,5,20,60,120,250`, from commit `684621e` (2026-11-15 19:43 IST, before any holdout-period output). Significance and effect floor (`alpha` 0.05, `min_abs_ic` 0.02, Bonferroni over all tests ever run) in the same commit and recorded in each hypothesis's `evidence`. Priors for generation (entry/exit share, max positions) in `algo/factory/generate.py`, `e68a19c` (10:09 IST = 04:39 UTC, before the first holdout-period chart at 08:25 UTC).
- **No manual removal.** Every generator refusal is listed above with its reason; no candidate was added, dropped or reordered by hand (created_by is `claude (agent), from alpha batch 1`).

## NOT established (blocks signing)
1. ~~Re-run of discovery at the recorded commit~~ **DONE 2026-11-16.** Worktree at `a693cdf`, freeze `bf2cd5c6` (newest at the time), the script's defaults at that commit (`--from 2020-10-01`, horizons 1,5,20,60, `--min-names 20`), dry run. Result: all 108 tests reproduce the stored batch 1 evidence exactly (same sample days, mean IC and p-value to the last digit, max difference 0), and the rule (Bonferroni over 108, p < 0.05, |IC| >= 0.02) gives the same 22 candidates as stored, which the generator turns into the same 16 definitions (6 refused). Later edits (`7cabf82`, `551070c`) did not change which candidates exist. Caveat: batch 1's own command line is not stored; the defaults reproduce it exactly, which is the evidence it used them.
2. **Batch 2 settings** (liquid top 200 universe, commit `872bc99`, 04:56 UTC). Batch 2 added no new strategy (section above), so it does not affect which candidates exist; its trace is only needed for completeness.
3. **Per-input availability list (section 7).** Not started.

## Per-candidate lock (section 7): `strategy_locked_at` is at least the "fixed" study's registration
| Definition | fixed-setting study registered |
|---|---|
| MOMENTUM_12M_M / LOWVOL_M / TREND_M | 11:30 / 11:49 / 12:39 (ineligible anyway, D7) |
| ALPHA_VOL_20D_H20 / VOL_60D_H20 | 12:59 / 13:03 |
| ALPHA_DIST_SMA_50D_H5 / MAX_DRAWDOWN_60D_H5 | 13:09 / 13:22 |
| ALPHA_RANGE_VOL_20D_H5 / RET_20D_H5 | 13:36 / 13:55 |
| ALPHA_RET_5D_H5 / VOL_20D_H5 / VOL_60D_H5 | 14:06 / 14:40 / 14:51 |
| ALPHA_DIST_SMA_50D_H1 / MAX_DRAWDOWN_60D_H1 | 15:06 / 15:55 |
| ALPHA_RANGE_VOL_20D_H1, RET_20D_H1, RET_5D_H1, VOL_20D_H1, VOL_60D_H1 | **not registered yet** |

Studies' own code commits, the later locks (paper settings, interpreter/engine commit) and `forward_evaluation_start` are still to be computed once the round is complete. **Batch 1's cutoff has not fired**: five definitions have no fixed study yet.

## Per-input availability list (section 7), traced from `research/study_runner.prepare` (2026-11-16, first pass)
| Input | Availability timestamp it carries | Finding |
|---|---|---|
| Daily bars (Kite, frozen) | `ingested_at`, pinned by the study's `known_at`; study reader uses `publish_lag = 0` (`study_runner.py:192`) | Snapshot-pinned. The capability must use the real session-plus-lag rule, not lag 0, for per-decision `as_of`. |
| Corporate actions | `knowledge_time` (+ `knowledge_time_source`, `announced_at`), `ex_date` | Point-in-time, as the reader already applies. |
| Adjustment factors | derived from the actions above | Must be rebuilt per decision day from actions known then (test required by section 10). |
| Instrument master (listing, delisting, symbol, ISIN) | `listed_on`, `delisted_on`, `first_observed_on`; **no announcement timestamp** | Gap: cannot be shown point-in-time. |
| AMFI market-cap lists (universe) | `effective_from`, `loaded_at` (load time, not AMFI's publication time) | Gap: published date unknown. A candidate's decisions depend on it, so under the policy this is `INSUFFICIENT_EVIDENCE` unless the publication date is evidenced. Needs a decision. |
| Half-year traded-value segments | derived from bars before a boundary date | Point-in-time by construction. |
| Cost schedules | `valid_from`/`valid_until`, `created_at` | Dated by validity; a schedule created later than its validity (backfills, `assumed_backfill`) is an assumption, to be labelled. |
| Benchmark index levels (floors) | `source_timestamp`, `ingested_at` per observation | Usable, with `known_at`. |
| Trading calendar | not yet traced | Open. |
| Fundamentals | not read by the 19 (definition language excludes filings) | Not needed. |

The AMFI list publication date and the instrument-master announcement times are the real blockers for treating the universe as point-in-time. They are open policy decisions for the owner, not code.

## Cutoff state (2026-11-17)
All 19 fixed-setting studies reached a terminal state (trials and verdict runs DONE, 2026-11-16 20:50 UTC last). Development verdicts: passed for `ALPHA_MAX_DRAWDOWN_60D_H5`, `ALPHA_VOL_20D_H5`, `ALPHA_MAX_DRAWDOWN_60D_H1`, `ALPHA_VOL_20D_H1` (4 eligible, above the minimum batch size of 3) and for `MOMENTUM_12M_M`, `MOMENTUM_LOWVOL_M` (ineligible, D7). The other 13 did not pass. The automatic cutoff is not built yet, so the snapshot is not recorded; this table is a manual read of `validation_report.passed`, not the immutable snapshot. No holdout table was read.

## Evidence gathering of 2026-11-17 (web and database), and why the audit is still NOT signed
**AMFI market-cap lists.** The universe of every study comes from these lists, used from `effective_from` (1 Feb / 1 Aug). Evidence for when each was published:
- AMFI's own page (`amfiindia.com/otherdata/categorisation-of-stocks`) lists the files with no publication date, and cites SEBI circular SEBI/HO/IMD/DF3/CIR/P/2017/114 of 6 Oct 2017 and the follow-up of 4 Dec 2017; neither gave a publication deadline in the sources reachable. Secondary sources say the list is "expected in the first week of January and July". The Wayback Machine could not be reached.
- The files' own HTTP `Last-Modified`: list of 31 Dec 2025 = 5 Jan 2026; list of 30 Jun 2026 = 7 Jul 2026 (both before their effective dates of 1 Feb and 1 Aug: **evidenced**). Every list from 2018 to 30 Jun 2025 carries the same bulk-migration stamp, 19 Aug 2025 (30 Jun 2024: 5 May 2026), so it shows nothing about when AMFI published them (**not evidenced**).
- Of the five lists in force during the holdout window (30 Jun 2024, 31 Dec 2024, 30 Jun 2025, 31 Dec 2025, 30 Jun 2026) two are evidenced and three are not. Policy section 7: an input whose availability time cannot be established is not point-in-time evidence and makes a dependent candidate INSUFFICIENT_EVIDENCE. **This needs an owner decision**: accept a bounded assumption (publication in the first weeks of January and July, a month before `effective_from`; the secondary sources and the two evidenced lists agree) recorded as a dated amendment and as accepted residual risk, or leave the universe as unevidenced (then no candidate is confirmable on this dataset). I did not choose for the owner.
**Instrument master.** No announcement time exists in the schema (`listed_on`, `delisted_on`, `first_observed_on` only); the same decision applies.
**Code lock.** The per-candidate lock records (`holdout_locks.py`, migration 090) were computed (nothing written) for all 19 definitions: **17 refuse, including all 16 `ALPHA_*`, because their studies were registered from a working tree that differs from its commit** (`code.dirty = true`). The same fact makes `holdout_batch.freeze` refuse them. They must be re-registered and re-run from a clean commit (same fixed settings; the lock then moves to the new registration time) before any batch can be frozen. The two that computed are `MOMENTUM_*` (ineligible anyway).
**What is established:** items 1 to 4 of the procedure audit (commit and configuration, source of every design parameter, re-run reproducing the same 16 hashes, no manual change). **What is not:** the point-in-time status of the AMFI lists (3 of 5) and the instrument master, and a clean code lock for the 16.
