# Holdout Policy v3: Statistical Correction, Candidate Budget and Information Access

**Status: APPROVED 2026-11-16 (section 9 signed), SPECIFICATION FROZEN. Implementation follows section 10, starting with step 0 (the provenance audit); nothing else is built yet.**
**Freeze rule.** The text is no longer redesigned. It changes only for (a) a factual error, shown with evidence, or (b) a failure found by the pilot, the calibration or the provenance audit, recorded as a dated amendment at the end of this file. New statistical machinery is not added without a specific failure it fixes.
Essential controls, which the freeze protects: untouched-data discipline, the fixed 30-slot budget with `0.05 / 30`, mechanical batch membership, a reproducible evaluation, the calibration, forward paper evidence before live money, and the access restrictions.
Written for the owner. It supersedes three parts of `docs/vti-alignment.md` section 3: rule (6), the "at most one global batch, ever" invariant, and "the holdout counts as consumed from the moment
`EVALUATING` is recorded" (replaced by section 7 here). The rest of that section stands. It does not touch the per-study inner holdout (2023-2024), the development-window rules, the development
gates, or `docs/research-policy-v2.md`.

**Two counts, kept apart.** The development deflated Sharpe uses the research family's trial count (`registry.deflation_trials`). The holdout uses the candidate budget in section 3. Neither count is read by the other, added to the other,
or used in place of the other, and the deflated Sharpe is not part of the holdout decision.

**Effective date: the day section 9 is signed, and it applies BEFORE Batch 1 is evaluated.** Batch 1 has not run. The method below is fixed before any holdout result exists, so nothing here can be chosen to suit a result.

## 1. Why the rule changes, and what is kept

The one-batch rule stopped repeated pass/fail feedback from becoming a tuning loop. The owner wants genuinely new strategies to be testable on the same 2025-01-01 to 2026-11-13 dates later. That is allowed, on these terms:
holdout evaluations are permanent and append-only, every candidate ever tested consumes a permanent slot in a fixed budget (section 3), and the correction acts on the acceptance decision, not just in a log. After Batch 1 these dates are a **repeatedly accessed validation set, not an
untouched holdout**. The only untouched data is forward, and it is **per candidate**: the sessions after that candidate was locked (section 7), not every day after 2026-11-13.

## 2. The acceptance decision (the part that was missing)

Today the three holdout gates (`verdict.holdout_gates`) are point-estimate floors: Sharpe at least `min_oos_sharpe`, drawdown at most `owner_max_drawdown`, Sharpe edge over the index at least `min_sharpe_over_benchmark`. None of them is a significance test, so counting trials changed nothing.
v3 adds one corrected test and keeps the floors.

**The drawdown floor is switched off today.** Thresholds v3 (`config/validation_thresholds.json`, 2026-11-16) set `owner_max_drawdown` to 1.0 (100%) because the owner moved drawdown control to a per-trade stop. The development gate still compares drawdown with the
index (`max_drawdown_vs_benchmark`, 1.25x), but the holdout gate reads only the absolute cap, so **on the holdout no drawdown is ever too large**. Decision D5 fixes this before Batch 1; the default is to judge the holdout drawdown the way development does,
at most 1.25x the index's drawdown. Both drawdowns are absolute magnitudes (the largest fall from a running peak, as a positive fraction) computed over exactly the same trading dates, with the same convention: a daily equity curve
built from daily returns and starting at 1.0 on the first holdout session (the strategy's after costs, the index's total return as the study names it). If the index's drawdown cannot be computed on those dates
(missing or misaligned index data, or an index drawdown of zero), the candidate is `INSUFFICIENT_EVIDENCE`, never a pass; no absolute cap is substituted and the check is never skipped.

**Primary test (the only corrected one).** For each candidate, over the holdout days, with daily returns after costs:

- H0: the true annualised Sharpe is at most 0 (the Sharpe as `annualised_sharpe` defines it today).
- Statistic: the observed annualised Sharpe. Null distribution: the daily returns with their mean removed, resampled with a stationary bootstrap, **1,000,000 draws, with a seed generated for each candidate** (below). (The present near-twin gate uses 1,000 draws and a 90% lower bound; that cannot resolve p = 0.0017 and is not used here.)
- **Frozen bootstrap parameters.** The block-length rule (a fixed mean block of `BOOTSTRAP_MEAN_BLOCK` sessions, today 21, about a month; no data-driven block selection), the draw count, the seed-generation procedure, the random-number generator (algorithm and library version) and the implementation version are written into the methodology version before Batch 1 and cannot change for this dataset except by the calibration route below (before any holdout read).
- **The exact algorithm (one implementation for calibration and production).** The platform's existing `stats.stationary_bootstrap` is pure Python (`random.Random`, a list per draw): fine for 1,000 draws, far too slow for calibration (years at 6 x 10^12 values). So a new vectorised NumPy implementation is written **and is the only one used** for both calibration and the holdout. Its specification:
  1. Input: the candidate's daily returns after costs over the holdout window, `n` values, complete (any missing session makes the candidate `INSUFFICIENT_EVIDENCE`; nothing is filled or dropped). Observed statistic `S = annualised Sharpe` of the raw returns.
  2. Null series: `y_t = r_t - mean(r)` (the sample mean removed once).
  3. Each draw builds `n` values: the first index is uniform on `0 .. n-1`; at every later step, with probability `q = 1 / 21` a new index is drawn uniformly on `0 .. n-1` (a new block starts), otherwise the index moves to the next session, **wrapping circularly from `n-1` to `0`**. This is the Politis-Romano stationary bootstrap, the same rule as the existing function.
  4. Statistic of each draw: `mean / sd x sqrt(252)` with the **sample standard deviation (divisor `n - 1`)**, the definition of `annualised_sharpe` in `algo/backtest/validation/stats.py`. A draw whose standard deviation is 0 counts as an exceedance (the conservative choice; with real returns it does not occur).
  5. `k` = number of draws with statistic `>= S`; `p_MC = (k + 1) / (B + 1)`.
  6. Generator, exactly: the candidate's seed is a 128-bit integer `s`. Block `b` (numbered from 0; block `b` holds draws `10,000 b` to `10,000 b + 9,999`) uses `Generator(PCG64(SeedSequence(entropy=s, spawn_key=(b,))))`. Within a block, the calls are made in this order and no others:
     (a) `starts = integers(0, n, size=D, dtype=np.int32)`; (b) `u = random(size=(D, n - 1))` (float64); (c) `jumps = integers(0, n, size=(D, n - 1), dtype=np.int32)`, where `D = 10,000`. (`dtype` is part of the specification: NumPy's default is int64, and the dtype changes the values drawn from the same stream.) Position `j >= 1` of a draw restarts when `u[j-1] < 1/21` and then takes `jumps[j-1]`; otherwise it takes the previous index + 1, modulo `n`.
     Every value is drawn whether or not it is used, so the stream consumed never depends on the data. The exact NumPy version is pinned and recorded (NumPy keeps a bit generator's output stable, but the algorithms of `Generator` methods may change between versions).
     Golden-value tests fix the first indices produced for a stated seed, so any change in the stream is caught.
  7. **Memory-bounded execution.** Draws are generated in the fixed **draw blocks of 10,000** of item 6. A block's statistics depend only on its own stream, so the result does not depend on how many blocks are processed at once.
     Only the running exceedance count `k` is kept, never the list of draw statistics. **Blocks are processed one at a time** (sequentially) by default. One block's arrays: `u` float64 36.7 MB, `jumps` int32 18.4 MB, index matrix int32 18.4 MB, resampled returns float64 36.8 MB, restart mask 4.6 MB, about **115 MB before NumPy's temporaries** (which can add as much again).
     The real peak memory is **measured on the final implementation** in the pilot, and the measurement is reproducible:
     - **peak resident set size** of the process (from the operating system, `ru_maxrss` / `/proc/self/status` `VmHWM`), not Python-tracked allocations, which miss most NumPy memory;
     - with the exact production configuration (`n = 460`, `D = 10,000`, the specified dtypes, the final code), over a **complete candidate evaluation** (all 100 blocks of 1,000,000 draws, plus the data loading), so memory kept between blocks or outside the bootstrap is caught;
     - recorded in the calibration report with the machine, CPU, total memory, operating system, Python and NumPy versions, the peak RSS and the time taken.

     More than one block at a time is allowed only if the pilot shows it is worth the memory, and the limit is set from that measurement, inside this machine's limits.
     Production for Batch 1 is at most about 7.4 x 10^9 resampled values: **at most 16 candidates** (the provisionally eligible `ALPHA_*`; the 3 `MOMENTUM_*` are not evaluated) x 1,000,000 x 460.
     NumPy is not yet a dependency of this project; adding it (pinned to an exact version) is part of the implementation.

  **Validation of the implementation, by its properties, not by a distribution test** (a two-sample test that finds no difference does not show the implementations are the same):

  | Test | Required |
  |---|---|
  | Small worked examples | for a fixed short series and a known stream of uniforms, the exact index sequence and statistic match values written by hand |
  | Initial index | uniform over all `n` positions (chi-square on many draws, and every position reached) |
  | Restart rate | about `1/21` at each later position, within a stated tolerance |
  | Continuation | always exactly the previous index + 1, wrapping from `n - 1` to `0` |
  | Restart | a new index drawn uniformly, independent of the previous one |
  | Length | every draw has exactly `n` values |
  | Same index sequence | the new implementation and the existing `stats.annualised_sharpe` give the identical statistic |
  | Zero variance | counts as an exceedance |
  | Chunking | 1, 2 and 8 blocks at a time give the same `k` for the same seed |
  | Seed | the same seed gives the same `k` in the recorded environment |

  The source checksums of the new implementation and of `annualised_sharpe` and `sharpe_per_period` go into the methodology version.
- **Seeds.** Each candidate gets its own seed, 128 bits from the operating system's random source, generated when its batch is frozen and committed in the frozen manifest, so **before the first-read marker and before any holdout value exists in the process**. It is never chosen, regenerated or replaced after that.
  Recorded with it: the generation procedure, the generator, the implementation version, the candidate and batch ids, and the execution environment (Python and NumPy versions, CPU architecture, the floating-point settings).
  The recorded seed makes every result reproducible **in that environment**. Floating-point summation can differ across environments and move `k` by a draw or two at the boundary, so the decision of record is the one computed in the evaluation; a reproduction check runs in the recorded environment.
- **The decision rule: the Monte Carlo p-value.** Let `k` be the number of draws at or above the observed Sharpe and `B` the number of draws. The p-value is `p_MC = (k + 1) / (B + 1)` and H0 is rejected when `p_MC <= alpha_c`.
  This is a proven-valid Monte Carlo test, not a point estimate treated as exact. If the ideal bootstrap p-value (infinitely many draws) is valid (super-uniform under H0), then for **any** `B`, `P(p_MC <= alpha) <= alpha`.
  **The probability is over both sources of randomness, the returns and the bootstrap draws.** That is why the seed must be generated independently of the returns and fixed before them (above): then, given the data, the draws are independent resamples and `k ~ Binomial(B, p)`.
  A seed chosen after seeing the data, or regenerated until a result appears, breaks this; a seed committed before any holdout read does not. (A single seed fixed for the whole dataset in advance would also satisfy the condition; a fresh committed seed per candidate makes the independence explicit and costs nothing.)
  Proof: rejection is `k <= k*` with `k* = floor(alpha (B + 1) - 1)`; given the ideal p-value `p`, `k ~ Binomial(B, p)`; `P(Binomial(B, p) <= k*)` falls as `p` rises, so its average over a super-uniform `p` is at most its average over a uniform `p`, which is exactly `(k* + 1) / (B + 1) <= alpha`.
  At `B = 1,000,000`, `k* = 1,665` and the size bound is 0.001666 (at most `alpha_c`). **The guarantee is about the overall rejection probability, not about each candidate:** a candidate whose ideal p-value is slightly above `alpha_c` can still get `p_MC` below it, and one slightly below can get `p_MC` above. Near the line, individual results can move either way; averaged over datasets, false passes stay within `alpha_c`.
  (A rule that compares a 99% Clopper-Pearson upper bound with `alpha_c` was considered. It is also valid, size 0.001572 at `B = 1,000,000`, but it rejects more good candidates for no gain in error control, so it is not used.
  The objection that it rejects about 1% of the time is a conditional figure: it is the chance of rejecting a dataset whose ideal p-value is exactly `alpha_c`. Averaged over all datasets under H0, datasets with an ideal p above `alpha_c` add about 1.4 x 10^-7 to the size.)
- The validity of the whole test therefore rests on one unproven part, whether the bootstrap's ideal p-value is valid for these returns. The calibration below looks for evidence against that; it cannot prove it.
- **Why calibrating at a true Sharpe of exactly 0 covers the whole null (true Sharpe at most 0), and when it does not.** Under a **location model**, returns `r_t = m + e_t` where the process `e_t` does not depend on the drift `m`:
  the null series `y_t = r_t - mean(r) = e_t - mean(e)` is the same whatever `m` is, so the bootstrap distribution does not change with `m`, while the observed Sharpe `S` rises with `m` on every path (its standard deviation does not depend on `m`).
  So the chance of rejecting can only fall as the true Sharpe goes below 0, and **0 is exactly the least favourable point**. Every series of section 2.2 is a location model, so for them this is proved, not simulated.
  **Scope:** real returns need not be a location model. If the drift moves with volatility (for example, falling markets that are also more volatile), a negative-Sharpe process is not a shift of a zero-Sharpe one and the argument does not apply.
  That case is checked by a **drift diagnostic** (section 2.2, regime switch with regime-dependent drift) at true Sharpes 0, -0.5 and -1.0. It is a separate family of 3 checks, kept out of the 7-check decision family so D8 and its boundary are unchanged, but **with its own failure rule fixed now, before any simulation runs**:
  - What it tests is what the guarantee needs: that the rejection rate at each of the three null points is **at most the nominal 1/600**. It is compared with 1/600, **not with the rate at Sharpe 0**: a rate that rises below 0 but stays under 1/600 does no harm, and one above 1/600 does, whatever the trend.
  - Rule: 310,000 datasets at each Sharpe. A check fails if its count reaches the smallest `c` with exact `P(Binomial(310,000, 1/600) >= c) <= 0.05 / 3`, which is **c = 567** (exact tail 1.5097%; at 566 it would be 1.6800%). By Bonferroni, a test of correct size fails at least one of the three with probability at most 4.53%.
    Sensitivity: an excess of 1.15x is caught with probability 87.2%, 1.2x 98.5%, 1.25x 99.9%.
  - **Any of the three failing is a calibration failure**, resolved like a decision failure, before any holdout read. All three counts, their exact p-values, exact (Clopper-Pearson) intervals and the trend are reported either way.
  Taken together, a correctly sized bootstrap fails calibration (the 7 decision checks or the 3 drift checks) with probability at most 7 x 0.6836% + 3 x 1.5097% = 9.31%. The cost of such a false alarm is a method change and a re-run before any holdout read, never a false pass.
- **Recorded for every candidate** (owner-only report): `k`, `B`, `p_MC`, the seed, the block configuration, the number of sessions, and the methodology and implementation versions.
- **Calibration before Batch 1.** The bootstrap is not assumed valid because it exists elsewhere in the platform. Its size is measured by simulation on returns whose true Sharpe is 0, with 460 sessions each, at three levels: 5%, 1%, and **0.1667% (the level actually used)**,
  on the seven series of the simulation design below (section 2.2). Each series: **310,000 independent datasets** (decision D8), each put through **the final decision procedure** (the frozen bootstrap and the `p_MC` rule) with 20,000 draws. The Monte Carlo rule is proven valid for every `B` (above), so a smaller `B` here tests the same procedure in the only way that matters: whether the bootstrap's ideal p-value is valid.
  Running 310,000 datasets x 1,000,000 draws is not feasible; it is not needed, because the draw count is the part that is proven. At `B = 20,000` the rule rejects when `k <= 32`, size bound 0.00165.
  **What is reported is the measured rejection rate of the procedure, not an assumed one.** If the procedure's true size were exactly 0.1667%, about 517 of 310,000 datasets would be rejected; the actual count is whatever the run measures.
  **The calibration decision is one simultaneous rule with an exact binomial boundary, not 21 separate intervals.** Separate 95% intervals would give a correctly sized bootstrap a false alarm somewhere about 17% of the time over 7 series (up to about 42% over all 21 checks).
  A Wilson bound does not fix this either: Wilson intervals are approximate, and at 300,000 datasets a Wilson rule at `z = 2.45` would fail at 555 rejections, whose exact chance under the nominal size is 0.810% per series, a family bound of about 5.7%, not at most 5%.
  - **Decision checks: the 7 series at 0.1667%**, the only level the holdout uses and so the only one the guarantee depends on. For each series the failure boundary is the **smallest count `c` with exact `P(Binomial(310,000, 1/600) >= c) <= 0.05 / 7`**, which is **c = 574** (exact tail 0.6836%; at 573 it would be 0.7691%, above 0.05 / 7).
    **Calibration fails if any of the 7 series has 574 or more rejections.** By the Bonferroni inequality the chance that a correctly sized bootstrap fails at least one series is at most 7 x 0.6836% = 4.78%, whatever the dependence between series.
    The boundary uses the nominal rate 1/600 = 0.0016667. That is deliberately slightly conservative: at 20,000 draws the `p_MC` rule's own size bound is 33 / 20,001 = 0.0016499, a little lower, so a correctly sized procedure fails even less often than the figures here.
  - **Diagnostic checks: 5% and 1%** on all 7 series, each reported with its exact one-sided binomial p-value and a descriptive Wilson interval. They are shown and explained, never decide. A clear excess there is a warning that the bootstrap's shape is wrong, to be read before the decision checks.
    Reason for the split: putting the diagnostic levels into the decision family would cost power at the level that matters without protecting the holdout any further.
  **Sensitivity of the decision rule, exact binomial** (per series, true rejection rate a multiple of 1/600):

  | Datasets per series | Fails at | False alarm per series | Bound over 7 | Detects 1.15x | 1.2x | 1.25x |
  |---|---|---|---|---|---|---|
  | **310,000 (D8)** | **574** | 0.684% | 4.78% | **80.1%** | 97.0% | 99.8% |
  | 300,000 | 557 | 0.637% | 4.46% | 77.9% | 96.4% | 99.7% |
  | 230,000 | 433 | 0.674% | 4.72% | 65.2% | 90.1% | 98.5% |

  Smaller excesses than these are not reliably detected, and the report says so. Wilson intervals stay in the report as descriptions only.
  **What passing calibration means:** no material size inflation was detected under the simulated series. It does **not** establish that the bootstrap p-values are valid for every market-return process. The design cannot cover every combination of serial dependence, volatility clustering,
  structural breaks, changing regimes, heavy tails and asymmetry, and real markets can differ from all seven series. Calibration is empirical evidence under a stated design, and the policy never describes it as a proof.
  The workload is about 2.0 x 10^13 resampled observations for the 7 decision series (7 x 310,000 datasets x 20,000 draws x 460 sessions), plus about 0.9 x 10^13 for the drift diagnostic (3 Sharpes x 310,000), run with the same memory-bounded blocks as production. That is a count of resampled values, not of CPU operations. A pilot with the real implementation measures time and memory first, and the full run is planned from that.
  It runs in deterministic seeded chunks so it can stop and resume. It is a batch job, not a unit test. Production is small: at most 16 candidates in Batch 1 x 1,000,000 draws x 460 sessions, about 7.4 x 10^9 resampled values.
  If calibration fails, the method (for example longer blocks or a studentised bootstrap) is changed and recalibrated, and this section is updated, **before any holdout read**. A change made then is made without any holdout result, so it is not choosing by result.
- Reject H0 when `p_MC <= alpha_c`, with `alpha_c = 0.05 / 30 = 0.001667` (Bonferroni, fixed family-wise error budget 5% over the dataset's entire candidate budget). The per-candidate level does not depend on how many candidates are in the current batch or have run so far,
  so batches can be added over time without changing earlier decisions.
- **What Bonferroni does and does not guarantee.** It holds under any dependence between the candidates' p-values (so correlated momentum variants need no independence assumption and no estimated "effective N"), **provided each hypothesis was fixed independently of the holdout observations and each p-value is valid**.
  It gives no protection against adaptive selection: if a later candidate was built, chosen or prioritised because of earlier verdicts, the 5% figure no longer holds. That condition is a rule the owner follows (section 4); the access limits in section 5 make breaking it by accident harder, but the owner's verdict page remains an information channel.
- **The 5% family-wise claim is conditional, everywhere it is used.** It holds only if (1) every tested hypothesis, and its selection into the tested family, was independent of the holdout observations, and (2) every candidate's p-value is valid under its null. The provenance audit gives evidence for (1) and calibration gives evidence for (2); neither proves it.
  No page, report or document may describe it as an unconditional 5% guarantee; wherever the figure appears, these two conditions appear with it.
- Accounting is **raw**: one candidate, one slot, no estimate of how alike they are. Which states consume a slot is defined once, in section 3. Because `alpha_c` is fixed at 0.05 / 30 from the start, the count never changes a candidate's bar; it enforces the budget. Consuming fewer than 30 leaves the error rate below 5%, never above it.

**A candidate PASSES only if** the primary test rejects H0 AND every floor holds (Sharpe, drawdown as decided in D5, edge over the index). The floors are not corrected: they can only remove passes, never add them. At a realised Sharpe of 2.17 the Sharpe floor (0.8) never binds; the edge over the index can.

**Evidence that is missing.** The equity curve must cover every session of the holdout window and the index must have returns on the same days; otherwise the candidate is `INSUFFICIENT_EVIDENCE`.

**What a PASS does not claim.** The "beats the index" gate is a floor on the point estimate, not a significance claim. No test here says the strategy is significantly better than the index. If the owner wants that claim, it needs its own test and its own share of the 5%.
A significance test on drawdown is not applicable: the cap is a risk limit, not a statistical claim.

**Other values:** `INSUFFICIENT_EVIDENCE` is never a pass. `NOT_APPLICABLE` is unchanged.

### 2.1 What this costs (the owner must acknowledge this)

Three different figures, kept apart:

- **Theoretical power** (the table below): a normal-approximation test on independent normal returns. It shows the order of the cost; it is not the power of the test that will run.
- **Primary-test power**: the measured chance that the complete primary test (frozen bootstrap, `p_MC` rule) rejects H0, found by simulation on the seven series of section 2.2 at true Sharpes 1.0, 1.4 and 2.0.
- **Full-policy pass probability**: the measured chance that a candidate PASSES the whole holdout decision, the primary test **and** the Sharpe, drawdown and edge-over-index floors, on the same simulations with the index of section 2.2. This is the practical acceptance chance, and it is lower than the primary-test power.

The second and third are published here before Batch 1. Only they describe the actual policy; the theoretical table is never cited as evidence of either.

The holdout has about 460 sessions (about 1.8 years of trading). Theoretical power: the realised Sharpe a candidate needs, and the chance that a strategy with a true Sharpe of the stated size gets through (one-sided).

How the figures are computed, so they can be reproduced: with `T = 460` sessions and annualised Sharpe `SR`,

- the realised Sharpe needed is `z(1 - alpha) x sqrt(252 / T)` (the standard error under H0, where SR = 0), and
- the chance of passing at a true Sharpe `SR` is `1 - Phi((needed - SR) / SE(SR))`, with `SE(SR) = sqrt(252 / T) x sqrt(1 + SR^2 / 2)` (the standard error under the alternative, Lo 2002, independent returns).

| Level per candidate | Realised Sharpe needed | True 1.0 | True 1.4 | True 2.0 |
|---|---|---|---|---|
| 5%, no correction | 1.22 | 41% | 57% | 73% |
| 0.05 / 19 | 2.07 | 12% | 26% | 48% |
| **0.05 / 30 (this policy)** | **2.17** | **10%** | **23%** | **45%** |

These figures assume daily returns independent and normal, 252 sessions a year. Real returns are neither. The primary-test power and the full-policy pass probability are published beside this table, and decisions about the policy are made on them.

Most genuinely good strategies would be rejected. The test protects against false passes; it does so by being a very hard bar to clear on short data. Two consequences the owner accepts by approving:

1. A FAIL means "not proven here", not "has no edge". It must never be read as evidence against the strategy.
2. Paper trading and forward evidence (section 7) carry most of the real confirmation. The holdout is a screen, not the proof.
3. **A PASS is not readiness for live capital.** About 460 sessions, the bootstrap's assumptions, dependence on one market regime and the dates' prior exposure (section 6) all remain. Forward paper evidence is required, not optional (D3).

Alternatives the owner may choose instead are in section 8 (D1). They are listed so the choice is made knowingly, before Batch 1.

### 2.2 Simulation design (frozen before the calibration runs)

All series are daily returns `r_t = m + s x x_t`, where `x_t` is a standardised process (mean 0, unconditional variance 1), `s = 0.01` (about 16% a year) and `m = SR x s / sqrt(252)`. **The true Sharpe is defined on the unconditional mean and variance**: `SR = 0` for size, 1.0, 1.4 and 2.0 for power.
The simulated returns stand for returns **already net of costs**. Every series has 460 sessions; every recursive series runs 500 discarded warm-up sessions first, from these starting values: AR `x_0 = 0`; GARCH `h_0 = 1` (the unconditional variance) and `x_0 = 0`;
regime switch `S_0` drawn from the stationary distribution (each state 1/2), transition matrix `[[0.99, 0.01], [0.01, 0.99]]`.

| Series | `x_t` |
|---|---|
| Normal | `z_t`, independent standard normal |
| AR(1), 0.1 | `x_t = 0.1 x_{t-1} + sqrt(1 - 0.1^2) z_t` |
| AR(1), 0.2 | `x_t = 0.2 x_{t-1} + sqrt(1 - 0.2^2) z_t` |
| Student t | independent `t_4 / sqrt(2)` (a t with 4 degrees of freedom has variance 2) |
| Skew-normal | independent skew-normal with shape -4.19, built as `delta |U0| + sqrt(1 - delta^2) U1` with **`delta = -0.9727`** (negative, so the skewness is -0.80; a positive delta would give +0.80), `U0`, `U1` independent standard normals, then standardised by its exact mean `delta sqrt(2/pi)` and standard deviation `sqrt(1 - 2 delta^2 / pi)` |
| GARCH(1,1) | `x_t = sqrt(h_t) z_t`, `h_t = 0.05 + 0.08 x_{t-1}^2 + 0.87 h_{t-1}` (persistence 0.95, unconditional variance 0.05 / (1 - 0.95) = 1) |
| Regime switch | `x_t = v(S_t) z_t`, two states with probability 0.99 of staying each day (average spell 100 sessions, equal long-run share), volatilities 0.525 and 1.313 (a 2.5 times jump, unconditional variance 1). Stands in for structural breaks and changing regimes |

**Diagnostic series, not in the decision family: regime switch with regime-dependent drift.** The same regime process, but the drift differs by state: `r_t = m(S_t) + s v(S_t) z_t`, with the calm state's drift `m_calm` and the volatile state's drift `m_vol = m_calm - 0.0015` (a volatile state 15 basis points a day worse).
`m_calm` is set so that the **unconditional** Sharpe (unconditional mean over unconditional standard deviation, both computed exactly for the two-state mixture) is 0, -0.5 or -1.0. It is the case the location-model argument of section 2 does not cover: drift that moves with volatility. 310,000 datasets at each of the three Sharpes, same keys convention with series number 7.

**The index** (for the floors in the full-policy pass probability) is simulated jointly with the strategy, the same series type, `s_I = 0.012`, true Sharpe 0.5, over the same 460 dates. The joint process, exactly:

- **Correlation 0.7 is between the underlying standard-normal draws**, not between realised returns: `z^I_t = 0.7 z_t + sqrt(1 - 0.49) w_t`, with `w_t` an independent standard normal. The realised return correlation that results is measured and reported for each series; it is not assumed to be 0.7.
- Normal, AR(1): the index is the same recursion driven by `z^I_t`.
- Student t: both use **the same** chi-square draw `V_t` (4 degrees of freedom): `x_t = z_t / sqrt(V_t / 4) / sqrt(2)` and `x^I_t = z^I_t / sqrt(V_t / 4) / sqrt(2)` (a bivariate t: tails arrive on the same days, as they do in markets).
- Skew-normal: each is `delta |U0| + sqrt(1 - delta^2) U1` with the same `delta = -0.9727` (standardised as above), with **the same** `U0` for both and `U1 = z_t` for the strategy, `U1 = z^I_t` for the index.
- GARCH(1,1): the index has **its own** variance recursion with the same parameters, driven by its own `x^I_{t-1}`; the two are linked only through `z^I_t`.
- Regime switch: **one shared regime state** `S_t` (a market-wide regime), the same two volatilities applied to both.

**Floors used in the full-policy pass probability** (thresholds v3, long-only, `config/validation_thresholds.json`, recorded with its version): Sharpe at least 0.8; Sharpe edge over the index at least 0.2; drawdown at most 1.25 times the index's (D5); each computed as in section 2 on the simulated series.
These index values are a design choice, not an estimate of the Nifty. The owner may change them before the calibration runs, never after.

**Randomness, exactly.** One root seed per run, a 128-bit integer `R`, recorded. Series are numbered 0-6 in the order of the table above; chunks of 1,000 datasets are numbered from 0 within a series; datasets from 0 within a chunk.
- Data generation for chunk `c` of series `i` (and the 500 warm-up sessions): `Generator(PCG64(SeedSequence(entropy=R, spawn_key=(i, c, 0))))`, with all the chunk's normal, chi-square and uniform draws taken in one fixed order written in the implementation and pinned by golden-value tests.
- Bootstrap draws for dataset `j` of that chunk: `SeedSequence(entropy=R, spawn_key=(i, c, 1, j))` used as the candidate seed of section 2, item 6 (its draw blocks add one more key, `b`).
A chunk's result depends only on its own keys, so a stopped run resumes at the next unfinished chunk and gives the same answer as an uninterrupted one. Chunk results are stored as they finish, with their keys.

## 3. Candidate budget and batches

- **Budget: at most 30 candidate slots across all batches, for the life of this dataset.** One definition of what consumes a slot, used everywhere (database, evaluator, UI):

  | Candidate state | Slot |
  |---|---|
  | Registered, not in a batch | not consumed |
  | Excluded at a batch freeze (with reason) | not consumed |
  | In a frozen batch, not yet evaluated | **reserved** (counts against what is left, can be released only by the next row) |
  | Its batch fails before the first-read marker | released, not consumed |
  | Its batch has committed the first-read marker | **consumed, permanently** |
  | Evaluation completed | consumed |
  | Evaluation failed after the first-read marker | consumed, permanently |

  **Every candidate whose batch reaches the durable first-read marker consumes one permanent slot.** A batch can be frozen only if its candidates fit in `30 - consumed - reserved`. When all 30 are consumed the dataset is exhausted: no further batch is created, and later strategies are judged on forward evidence only.
  `alpha_c` stays 0.05 / 30 whatever number is actually consumed.
- **Batch membership is mechanical.** A batch holds every eligible candidate (section 4) whose development verdict passed by its cutoff. Nobody chooses among them. **Exclusion is allowed only for one of these reasons, fixed now:**
  1. a defect in the definition or its data (it does not do what it says, or reads data that is wrong), shown with evidence;
  2. an implementation error in the study that produced the development verdict, shown with evidence;
  3. ineligibility under section 4 (provenance or independence failure);
  4. a breach of another rule written in this document before the cutoff.

  **A candidate that met the development pass criteria cannot be excluded because its development result looks unattractive**, or because of anything about holdout-period behaviour. Each exclusion records its reason number, the evidence and the time, at the cutoff and before the batch is evaluated, and the record is immutable.
  For Batch 1 this means every eligible current definition that passes development validation (section 4.1), leaving the rest of the 30 for later batches.
- **No holding back.** At each cutoff, every candidate whose development verdict has passed by then (and was not already in a batch or excluded) is either in that batch, carried over under the minimum-size rule below, or **excluded from this dataset for good**, with the reason recorded. A later batch may contain only candidates whose
  development verdict passed after the previous batch was frozen, plus those carried over automatically. Otherwise a strategy could be kept aside and submitted after an earlier batch showed which kind of idea passes, which is choosing by verdict.
  An excluded candidate consumes no slot (it was never tested) and can still be judged on forward evidence.
- **Fixed cutoffs, not owner-chosen freeze dates (decision D6).** A batch can only be frozen at a predetermined cutoff, and **a cutoff is an automatic event, not an action**. Batch 1's cutoff fires by itself when the last of the 19 definition studies of the current round reaches a terminal state (a recorded development verdict, or a run ended `FAILED` or `CANCELLED`; a study that ends without a verdict has no passed verdict and is simply not a member).
  **Two separate events, in this order:**
  1. **Cutoff snapshot (automatic).** At the cutoff the system records, immutably and timestamped: the candidate population, each candidate's development verdict, registration time, provenance status, and every exclusion and carry-over. The owner cannot delay it, trigger it early, supply a list, or change it afterwards.
  2. **Batch freeze (after the audit).** The batch is frozen, its manifest hashed and its seeds committed, only when the provenance audit (section 4.1) is signed and every eligibility decision recorded in the snapshot is resolved. Until then the batch is `PENDING`. Resolving can only apply the audit's result to the snapshot's members (a member found ineligible is excluded under reason 3); it can never add a candidate, and a late audit changes nothing about who was in the snapshot.
  Later cutoffs are fixed calendar dates (default: the last trading day of each quarter), fired the same way. At a cutoff, every candidate whose development verdict passed since the previous cutoff is in the batch or excluded for good with its reason recorded at that cutoff. The owner cannot delay a candidate to a later cutoff.
- **Minimum batch size 3.** A batch with fewer than 3 candidates cannot be frozen, so a single idea is not tested against a single answer. If fewer than 3 qualify at a cutoff, no batch is frozen and those candidates **carry over automatically** to the next cutoff
  (nothing is evaluated in between, so carrying them gives no information); exclusion stays possible only with a recorded reason at a cutoff. The minimum size is an operational rule, not a statistical safeguard: the control that matters is that no candidate is included, delayed or excluded because of an expected result.
  Exception (decision D2): the last batch may be smaller only if it uses the entire remaining budget.
- A batch is numbered 1, 2, 3 in order, never deleted, never re-run; its manifest is frozen with a hash before evaluation and cannot be changed. The verdicts, reports and manifests of completed batches are immutable.
- The consumed and reserved counts are derived from the permanent ledger of candidate states inside the same transaction that freezes a batch, never taken from a caller. Two batches frozen at once cannot get the same number or a wrong count.

## 4. Candidate registration and families

Reuse what exists; add nothing duplicate. The locked study document already carries the definition, parameters, universe, costs, code commit and checksum (`study_sha256`), and `research_family` carries the hypothesis and the audited justification. Added:

- a **registration timestamp** per candidate (before its batch is frozen),
- a **classification review**: the owner records whether the candidate is a new family or a member of an existing one, with a reason. A change of exit percentage, number of positions or other numbers of an existing idea is the same family, and its trial count carries forward. Rewriting the same strategy in different code is not a new strategy.

**Independence from holdout-period information (the condition the correction depends on).** The guarantee in section 2 needs each hypothesis to be fixed independently of the **holdout observations**, not only of earlier verdicts.
A candidate is eligible only if its hypothesis, construction, selection into a batch and priority were independent of all information about how it, or a related strategy, behaved after 2024-12-31. That includes:

- earlier PASS/FAIL verdicts;
- strategy outputs dated after 2024-12-31: signals and decisions, equity curves and returns, paper-run proposals and performance, scorecards, screener-strategy matches;
- charts, screens or other analyses of the holdout dates **used to form or select the idea** (for example noticing that a kind of breakout did well in 2025 and building a breakout strategy from it).

**A candidate whose construction or selection was influenced by such information is ineligible for this dataset.** It is not evaluated here; it is judged on forward evidence only. It is not run as an "exploratory" holdout test, because evaluating it would add information and use a slot while supporting no claim.

**What cannot be excluded, stated plainly.** The owner sees market prices every day (and holds a live account). General awareness of how markets moved in 2025-2026 cannot be removed, and it can shape which ideas seem worth trying. For a candidate chosen by a person, this weakens the confirmatory claim and is recorded as a limitation;
for a candidate produced mechanically from development data (section 4.1), the choice of hypothesis did not pass through a person. Neither case is treated as clean in the Batch 1 record.

Before its batch is frozen, each candidate's **research provenance** is recorded: how and when it was created (by a person, or mechanically from development data, with the source), its definition checksum and code commit, the study and its registration time, and **every recorded exposure of its own or a related strategy's holdout-period outputs, with timestamps, compared with its creation time**.
Code cannot prove the condition: access controls cannot show what a person remembers. It remains a research-governance requirement; section 5 removes the easy ways to break it by accident, and the provenance record makes it explicit and auditable.

### 4.1 Provenance audit of the current 19 (from the database and git, 2026-11-16, times UTC)

**Correction to the previous draft.** It said every chart came after all 19 definitions existed. That was wrong: the first two charts (08:25 and 08:37) came **before** the three momentum definitions were written (09:06). The chronology below is the corrected one.

| Time (2026-11-16) | Event |
|---|---|
| 2026-11-15 | Price features and their manifests (`algo/features/price.py`, `config/feature_manifests.json`), alpha discovery (`algo/alpha/run.py`, `registry.py`) written; discovery runs on development data only, behind the research lock |
| 04:54 | The 16 `ALPHA_*` definitions created mechanically, one per alpha candidate (`scripts/generate_strategies.py`); definitions are insert-only (trigger on `strategy_definition`) and hashed |
| 08:25, 08:37 | 2025-2026 decisions of `ALPHA_RANGE_VOL_20D_H5` (1 stock) and `ALPHA_DIST_SMA_50D_H5` (2 stocks) drawn on the Data Explorer |
| 09:05-09:06 | The 3 `MOMENTUM_*` definitions written by hand and created (`algo/factory/preregistered.py`) |
| 09:20-12:31 | 2025-2026 decisions of `MOMENTUM_12M_M` (3 stocks), `MOMENTUM_LOWVOL_M`, `ALPHA_VOL_60D_H5`, `ALPHA_VOL_20D_H5` drawn |
| 11:30-13:55 onward | Fixed-setting studies registered by one script for the definitions in turn, each at its own setting (`own_setting`); none chosen |

**The 16 `ALPHA_*`: provisionally eligible, pending the procedure-provenance audit.** Two different things are audited, and only the first is established today.

1. **Candidate generation (established).** Created at 04:54, before any holdout-period strategy output was seen; immutable from creation (insert-only, hashed); settings fixed by rule; all run; none picked. The four later charted were charted after creation, and from now on nothing about them is decided by a person (mechanical membership, closed exclusion list).
2. **Procedure design (not yet established).** Whether the feature list, horizons, discovery criteria and generator were fixed without knowledge of 2025-2026 outcomes. Evidence so far: the feature formulas were frozen in `docs/vti-phase1-spec.md`, committed 2026-11-14, before any holdout output existed in this system.
   Not yet traced: the source of the horizons (1, 5 and 20 days) and of the significance and effect-size rules. And some code was edited after the 16 were generated (`alpha/registry.py` and `alpha/run.py` to 09:01, `generate_strategies.py` to 06:34).

**The procedure-provenance audit, done at the cutoff and signed before Batch 1 is frozen.** It must show:
- the exact commit and configuration that ran the discovery producing these 16 candidates;
- the source of each design parameter (features, horizons, significance rule, effect-size floor, the generator's rules), each traced to a document or commit dated before 2026-11-16 08:25 (the first holdout-period output), or shown to be a generic default with no holdout-dependent choice;
- that no later edit changed which candidates exist or which were turned into definitions, shown by **re-running discovery and generation at the recorded commit on the same development data and getting the same 16** (same hashes);
- that no candidate was removed, substituted or prioritised by hand.

If any of these fails, the candidates concerned are not confirmatory and are treated like the momentum three (forward evidence only). If all pass, they become eligible.

**What this audit cannot settle, stated plainly.** The procedure was designed by people and by an AI assistant whose training data may include commentary on 2025-2026 markets. No document or commit can show that this awareness did not shape a generic choice such as "use standard price features".
The audit does not claim it. It establishes that every design parameter was fixed before any holdout-period output of this system existed, and traced to a written source, and the owner accepts the remaining risk explicitly in section 9.
A stricter reading, that no procedure designed after 2025 by anyone with market awareness can be eligible, would leave no candidate eligible for this dataset, ever. If the owner prefers that reading, the consequence is that the 2025-2026 dates are used for no confirmatory test at all, and all confirmation is forward.

**The 3 `MOMENTUM_*`: not established as independent, so excluded from the confirmatory family (decision D7).**
- They were chosen and written by hand (by the AI assistant in a working session, with the owner), on 2026-11-16, **after** two related strategies' 2025-2026 decisions had been drawn, by people living through those markets and an assistant whose training data may cover them. "Inspired by published research" is true (12-month momentum is one of the best-documented effects) but it is not an independence argument: from many published ideas these three were picked, and the choice could have been shaped by the holdout period.
- They are **ineligible for this dataset**, with **no override**: labelling a candidate whose independence is not established does not restore the condition the correction needs, so no recorded reason can put one into the confirmatory family. They are judged on forward evidence only, from their own lock time (section 7).
  This applies to `MOMENTUM_12M_M` too, the strategy whose development verdict passed first. Any later look at them on the 2025-2026 dates would be a separate, explicitly non-confirmatory exercise that uses no slot and gives no PASS; this policy does not provide one.

**Selection.** No one may choose among the eligible candidates: a person who has seen six candidates' 2025-2026 decisions cannot choose among them without using that. Batch 1 is every eligible candidate whose development verdict has passed at the cutoff (section 3).
The audit is rebuilt from the database and git at the cutoff, and anything found after this date is added before the batch is frozen.

## 5. Information access

**Output.** The evaluator and every reader return **candidate-level PASS / FAIL (and INSUFFICIENT_EVIDENCE) only**. Gate names may be given as a diagnostic (which kind of check failed). **No numerical results, no thresholds, no p-values, no equity curves, no daily returns, no trades, no per-stock figures.**
The detailed report stays in `holdout_report`, owner-only, and is not served by any route. A PASS or a FAIL is still information; verdict-only output reduces the leak, it does not remove it.

**Access.** Only the owner (a new permission held by the owner alone) and the promotion path may read verdicts. No research, discovery, feature, alpha-generation or strategy-generation code may import or call the verdict reader.
Enforced by moving the reader out of the research packages and a test that fails if any research module imports it, the same way the existing import rules work. Today `read_verdicts` is available to research code; that changes.

The promotion path already shows verdicts on two pages: Paper trading > Settings ("Strategies from research", via `GET /api/paper/definitions`) and the study page's "What happens next". Both show only candidate-level state (waiting / failed / passed), which this section permits,
but today any user with `strategy:own` can see them. They move behind the owner permission.

## 6. Known leaks of the 2025-2026 dates (recorded, not hidden)

1. **Data Explorer strategy signals.** The route that draws a definition's buy/sell decisions (`GET /api/strategies/definitions/{id}/{version}/signals`) computes them up to the latest bar, which includes 2025-2026, and keeps them in
   `definition_signal_series` / `definition_signal_day`; the saved-strategy and screener signal routes do the same for their strategies. A strategy's decisions on these days can be looked at before any holdout, and a passed strategy's decisions on
   them would teach the next one. **Restriction, for every strategy, passed or not:** research-facing APIs, the Data Explorer, discovery, feature, alpha-generation and strategy-generation code must not expose or consume strategy decisions dated **after 2024-12-31**.
   This applies to strategies that pass a holdout batch as well, and it covers the forward days too: forward evidence is the reserved confirmation, and other strategies' forward decisions would teach a new candidate just as holdout ones would.
   Decisions after 2024-12-31 are reached only through owner and promotion workflows isolated from research: paper trading (its own account's proposals and orders) and the promotion pages, which show verdict state only.
   The stored decisions stay in the database (the tables are history); only access is restricted. Those already viewed are listed in section 4.1 and in the Batch 1 record as seen.
   **Consequence for the owner:** the Data Explorer draws no buy/sell marks after 2024-12-31 for any strategy, including the saved trend and screener strategies. A strategy's recent decisions are seen on the Paper trading page of the account running it.
   **Indirect routes count too.** The restriction covers anything derived from a strategy's decisions or results after 2024-12-31, not only the signal endpoint: signal counts and buy/sell summaries, feature values or tables built from signals, strategy performance summaries and scorecards,
   a saved screener strategy's matches, and stored backtest runs that reach past 2024-12-31 (the 8 studies registered before the lock run to 2025-01-29; their runs are hidden from research views for the days after 2024-12-31).
   Implementation starts with an audit of every route, page and script that serves a strategy's outputs, listed in the Batch 1 record. Market data itself (prices, fundamentals, an ad-hoc screen over market data) is not a strategy output; seeing it is the known leak in item 2, not something this rule can remove.
2. **Paper-run proposals** and the owner's own look at charts and earlier paper accounts on 2025-2026 are already seen. These cannot be restricted or undone; they are recorded here so the dates are never described as pristine.
3. **Verdict feedback itself**, once Batch 1 is evaluated.

## 7. Failed execution, consumption and the reserved future dataset

- A run that **fails before any holdout data was read** consumes nothing: no candidate is spent and the batch can be restarted from the same frozen manifest.
- The first holdout read is preceded by a durable marker, committed before the read. (Today the batch is treated as consumed when `EVALUATING` is committed, before anything is read; v3 moves that point to the marker.) **After the marker exists, the candidates of that batch are permanently consumed**, even if the evaluation crashes or fails.
- **The marker precedes every route to holdout data, not just the price reader.** The evaluator is given a **capability-scoped interface, not a database connection**: the capability reader is the only component through which holdout-period source data (bars, corporate actions, index levels) can be retrieved, and it refuses to work until the marker is committed.
  **The capability enforces the boundary itself**, so no caller has to remember to filter: it serves only **source** inputs, only for the holdout window plus the warm-up the candidate's definition declares before it, and nothing else. **Two different cutoffs apply, and the capability keeps both:**
  - **`known_at`** (per study) identifies the **frozen source-data snapshot**: only what the database held at that moment. It is not a per-decision cutoff, and it does not replace the next one.
  - **The per-decision availability cutoff** (`as_of` in the reader, the simulated decision time): for each simulated decision the capability serves only information that was available to the strategy **at that time**, by announcement, publication, effective-date and revision history. The reader already does this for bars (a bar is visible only after its session plus the publish lag) and for corporate actions (visible only once their `knowledge_time` has passed); the capability must not weaken it.
    Examples that must hold: an action announced after a decision date does not affect that decision, nor do the adjustment factors for it; index membership and market-cap lists are those in force on the relevant date by announcement date, not the final historical record; a restated filing is invisible before its publication date; a later correction to historical prices does not reach earlier decisions.
    Announcement or publication time and effective date are separate timestamps and are used separately, according to when the information was actually available.
  - **Unknown availability time.** Where the platform cannot establish when an input became available, that input **cannot be treated as point-in-time evidence**: a candidate whose decisions depend on it is `INSUFFICIENT_EVIDENCE`, never silently allowed. Section 10, step 0 lists, input by input, which timestamp each one carries (`knowledge_time` for actions, announcement date for membership, publication date for filings, the session plus publish lag for bars) and which, if any, has none.

  The contract lists every input the study path uses:
  - daily bars and their adjustment factors; corporate actions and their review decisions;
  - instrument master and identity history (listing and delisting, aliases and symbol changes, ISIN changes) and instrument terms (lot size, tick size);
  - the universe inputs: the AMFI market-cap lists in force each day and index membership, with their announcement and effective dates;
  - the trading calendar (holidays, special sessions);
  - cost schedules; index levels (for the benchmark floors);
  - point-in-time fundamentals with publication dates and restatement history **if** a candidate's definition reads them (the current definition language does not allow filed fundamentals, so none of the current 19 needs them).

  The exact list is **derived by tracing the study path** (`study_runner.prepare`, the universe build, the reader, the engine and cost model) and fixed in the contract before Batch 1; an input the study path reads that is not in the contract makes the evaluation fail, never quietly reach the database.
  The capability also checks that the source history covers each candidate's declared warm-up before the window; if it does not, the candidate is `INSUFFICIENT_EVIDENCE`.
  A request for any date outside the permitted range (the window plus that candidate's declared warm-up), or for an instrument outside the candidate's universe as known at `known_at`, is **rejected with an error**, not trimmed or quietly answered; the dates are enforced by the capability, never left to the caller.
  It has no method that returns `definition_signal_series` / `definition_signal_day`, paper-run outputs, feature values, stored backtest runs, scorecards or any other derived table.
  The evaluator has no other way to query the database, so a new helper cannot bypass the boundary by reading a table directly. A test checks that the evaluator receives no connection, and that every holdout read fails without the marker.
- **Generating versus reading.** During an authorised evaluation, after the marker, the evaluator **generates** each candidate's decisions and returns on the holdout days from source data through the capability. It never **reads** previously generated holdout-period decisions, cached signals, paper-run results, feature values or earlier backtest outputs; those are not reachable through the capability at all.
- Limit, stated plainly: this boundary is enforced in the application. Anyone with the database password can still read every table. A database role that can see only the development window is a later hardening, already noted in `docs/vti-alignment.md` section 3.
- **Resume after a crash** is allowed only if no verdict or report of the batch was written, with the same frozen manifest, evaluator version and data snapshot. It is the same deterministic calculation finished, not a second look, and it gives the same answer. Anything else makes the batch `EVALUATION_FAILED`.
- A failed batch stays in the history with its state, its candidates' slots stay consumed (section 3), and it is never re-run.
- **Forward evidence is per candidate.** It is the independent confirmation, and it is never appended to this dataset. Each candidate records `strategy_locked_at` (when its definition and settings became immutable), `forward_evaluation_start` (the first trading session that **opens after** `strategy_locked_at` and after 2026-11-13), the definition checksum and the code commit at the lock.
  Only sessions from `forward_evaluation_start` count. A candidate locked on 1 December cannot count 14-30 November. Any change to its parameters, universe, entry or exit rules or risk rules makes a new candidate (a new version) with a new lock and a new start; the old forward record stays with the old version.
  **`strategy_locked_at` is the latest of every lock that can affect a decision**, not only the definition's creation: (a) the definition (insert-only, hashed); (b) the settings it trades at (`own_setting`, derived by rule from the definition, and recorded in the study); (c) the universe, costs and risk settings (per-trade stop, cooldown), fixed when its study is registered and locked in `study_sha256`;
  (d) the code that turns them into decisions (the interpreter, the engine, the paper runner), pinned by commit. A later change to any of them that can change a decision makes a new lock; a change that provably cannot (for example a page's wording) does not, and that judgement is recorded with the commit.
  The paper account must trade at exactly the locked settings (the same stop and cooldown as the study); a difference is a deviation under D3 item 6.
  For the current 19 the definitions were created on 2026-11-16, but their fixed-setting studies were registered later that day and after, so **each one's `strategy_locked_at` is at least its study's registration time**, and its `forward_evaluation_start` the first session that opens after that; these values are computed per candidate in section 10, step 0, not assumed to be 2026-11-17.
  Before any live money, a strategy needs the forward evidence of D3, counted from its own start.

## 8. Decisions still open (marked where this document chose a default)

| # | Question | Recommended (owner's review, 2026-11-16) |
|---|---|---|
| D1 | The power cost in 2.1 is large. Keep FWER 5% over 30 (Bonferroni), relax to FWER 10%, or screen with a false-discovery-rate rule and rely on forward evidence for the confirmation? (The alpha-discovery code already moved from Bonferroni to Benjamini-Hochberg for the same reason.) | FWER 5% over 30, Bonferroni, subject to the fixed-hypothesis condition (sections 2 and 4) |
| D2 | May the last batch be smaller than 3 if it uses the remaining budget? | Yes, only if it consumes the entire remaining budget |
| D3 | The minimum forward evidence before live money. **Must be decided before section 9 is signed.** No live trading of any research strategy until then | Proposed: the six requirements and their exact measurement rules in section 8.1, all required, never waived |
| D4 | Which candidates go in Batch 1 | **No longer a choice.** Every eligible candidate whose development verdict passed at the cutoff, mechanically (section 3), because the owner has seen holdout-period decisions of six of them (section 4.1) |
| D5 | The holdout drawdown floor: today it is off (cap 100%). Judge it against the index, set an absolute cap, or leave it off? | At most 1.25x the index's drawdown, absolute magnitudes over the same dates and the same equity convention; no reliable index drawdown is `INSUFFICIENT_EVIDENCE` |
| D6 | Batch cutoffs | Batch 1: the day the current round's last verdict is recorded. Later: the last trading day of each quarter |
| D7 | The forward-only path for candidates ineligible here (the 3 `MOMENTUM_*`). Their exclusion is not a choice (section 4.1, no override). **Consequence to weigh:** today paper trading of a research strategy opens only after it passes the global holdout, so without a forward-only path they can never be paper traded. | Add the path: paper trading as their forward test, from their own forward start, labelled "not holdout-tested", no live money until D3 is met |
| D8 | Calibration datasets per series | 310,000 (exact binomial rule, fails at 574: 80.1% power to catch a 1.15x inflation at 0.1667%, 97.0% at 1.2x); if the pilot shows it does not fit, 230,000 (fails at 433: 65.2% at 1.15x, 90.1% at 1.2x), stated as weaker |

### 8.1 D3: forward evidence before live money, with its measurement rules (proposed)

All are measured from the candidate's own `forward_evaluation_start`, computed by the system from paper records (never entered by hand), shown with their values, and all are required: any one short blocks live promotion.

| # | Requirement | Exactly how it is measured |
|---|---|---|
| 1 | At least **126 forward sessions** | NSE trading sessions on the platform's market calendar from `forward_evaluation_start`. A session counts only if the paper runner made a decision for it (`PROPOSED` or `NO_CHANGE`); `ERROR` and `SKIPPED` sessions do not count. If more than 5% of the calendar sessions in the period are `ERROR` or `SKIPPED`, the evidence is insufficient however many sessions have counted |
| 2 | At least **30 completed round trips** | A round trip is one instrument's position going from zero to above zero and back to zero. Buying more while held (scaling in) and partial sales stay inside the same trip; it completes only when the holding is zero again. Splits and bonuses adjust the quantity and do not end a trip; a holding created by a corporate action (for example a demerged company's shares) is not a round trip and is reported separately. A strategy that trades rarely simply waits longer |
| 3 | Realised costs within **1.5x** of the model | Sum of the realised charges of every paper fill in the period, divided by the sum of the study's cost model applied to the same fills (same quantities, prices and dates). The modelled sum must be **strictly positive and present for every fill**; otherwise the evidence is insufficient. The numerator and denominator are recorded and shown, not only the ratio |
| 4 | Slippage within **2x** of the model | Per fill: `(fill price - reference price) / reference price` for a buy and its negative for a sell (positive = against the strategy), where the reference price is the decision-day reference price on the order. The quantity-weighted mean over all fills, divided by the slippage model's quantity-weighted mean for the same fills. Partial fills count by the quantity filled. Cancelled and expired orders have no fill and are counted under item 6, not here.
The modelled mean must be **at least 1 basis point**: if it is zero, negative, missing for any fill, or below 1 bp, the ratio is not a meaningful cost control and the evidence is insufficient. The realised and modelled means are recorded and shown separately, not only the ratio |
| 5 | Forward drawdown at most **1.25x** the index's | Both as in section 2: daily equity curves starting at 1.0 on `forward_evaluation_start`, the paper account marked at each session's close **including open positions**, and the index's total return on exactly the same sessions; absolute magnitudes. No reliable index data means insufficient evidence |
| 6 | **Zero strategy deviations**, and owner non-execution within a stated limit | Every session, the decisions are recomputed from the locked strategy and compared with the paper run. Recorded separately, by type: **strategy-side** (a recomputed decision missing from the proposals, a proposal the locked strategy did not make, a different quantity or side, a setting that differs from the lock); **owner-side** (a proposal rejected, left to expire, approved with a changed quantity, or a manual order). Strategy-side must be **zero**. Owner-side is reported in full, item by item; proposed limit: at most **2%** of proposals, otherwise the evidence describes the owner's choices, not the strategy. A silently missed signal is a strategy-side deviation, never invisible |

The figures (126, 30, 1.5x, 2x, 1.25x, 2%) are proposals for the owner to set, not derived from data.

## 9. Approval record (the gate)

**SIGNED 2026-11-16 (effective date).** The owner approved all recommended defaults in a working session.

| Item | Value |
|---|---|
| Approved by | Owner (Ilesh Patel), 2026-11-16, "yes, do recommended, I approved defaults" |
| Date (becomes the effective date) | 2026-11-16 |
| D1 chosen | FWER 5% over 30, Bonferroni, conditional on the fixed-hypothesis condition |
| D2 chosen | Yes, last batch may be smaller than 3 only if it consumes the entire remaining budget |
| D3 chosen | Section 8.1, all six requirements, never waived |
| D5 chosen | Holdout drawdown at most 1.25x the index's; no reliable index drawdown is `INSUFFICIENT_EVIDENCE` |
| D6 chosen | Batch 1 at the last terminal study of the current round; later the last trading day of each quarter |
| D7 chosen | Forward-only paper path for the 3 `MOMENTUM_*`, labelled "not holdout-tested", no live money until D3 |
| D8 chosen | 310,000 datasets per series (fallback 230,000, stated as weaker, only if the pilot shows it does not fit) |
| Power cost in 2.1 acknowledged | Yes |
| The 5% family-wise claim accepted as conditional on hypothesis independence and valid p-values (section 2), not as an unconditional guarantee | Yes |
| Section 4.1 read: the 16 provisional until the procedure-provenance audit passes; the residual risk it cannot settle accepted, or the stricter reading chosen | Residual risk accepted; the 16 stay provisional until the audit passes |

## 10. What gets built after approval (not before)

0. **First, the procedure-provenance audit** of the 16 `ALPHA_*` (section 4.1: commit and configuration, the source of every design parameter, the re-run reproducing the same 16 hashes, no manual change), rebuilt from the database and git and signed before anything else, **together with the per-input availability list of section 7** (which timestamp each source input carries, and any that has none). Then `strategy_locked_at` (the latest of the four locks in section 7) and `forward_evaluation_start` computed and recorded for each of the 19.
1. Migration: drop the one-batch constraint; add batch number, the candidate-state ledger (section 3), registration timestamp, classification review and research provenance (with the exposure record of section 4, rebuilt from the database at each cutoff), exclusions and carry-overs with reasons, cutoffs, the first-read marker, methodology version; immutability triggers; transactional numbering.
2. `holdout_batch.py`: cutoffs fired automatically (Batch 1 when the last of the 19 studies is terminal, later ones on the calendar) with membership taken from the database at that moment; sequential batches frozen only at cutoffs, membership computed mechanically (every eligible candidate), budget from the ledger (consumed + reserved), minimum size with automatic carry-over, the no-holding-back rule, consumption at the marker.
3. `holdout_evaluator.py` and `verdict.holdout_gates`: the corrected primary test with the new vectorised bootstrap of section 2 (checked against the existing function), per-candidate seeds committed at freeze and the `p_MC` rule; the evaluator given a capability-scoped interface instead of a connection, with the marker before every holdout access, serving the traced point-in-time input contract of section 7 and checking the warm-up; the drawdown floor as decided in D5, the coverage rule for missing evidence, every recorded input of section 2, verdict-only output.
4. Access control: new owner permission; reader moved out of research packages; import-boundary test; `GET /api/paper/definitions` and the study page's next steps behind the owner permission; the audit of section 6 first, then every route, page and script serving a strategy's outputs (signals, counts, summaries, scorecards,
   screener-strategy matches, stored runs) blocked after 2024-12-31, for all strategies.
5. Tests: batch lifecycle, the slot table in section 3 state by state, cutoffs and carry-over, no holding back, immutability, concurrency, information leak, resume-only-if-nothing-written, the drawdown rule (same dates, same convention, absolute magnitudes, missing or zero index drawdown); `p_MC` against known cases and the exact size `(k* + 1) / (B + 1)` for a uniform p; the bootstrap property tests of section 2 (worked examples, start, restart rate, continuation and wrap, length, identical statistic, zero variance, chunking, seed, golden values of the exact stream construction); the skew-normal series has skewness -0.80, not +0.80; the automatic cutoff (fires once, takes membership from the database, cannot be delayed or given a list); every input the study path reads is in the capability contract; seeds generated and committed at freeze and never replaced; the evaluator gets no connection, and no holdout read succeeds before the marker.
   Point-in-time tests on the capability: an action with a later `knowledge_time` added to the database changes **no** decision or adjusted price before that time; adjusted history requested for decision day D is identical with and without actions announced after D; index membership and market-cap lists follow announcement dates; a later restatement does not alter earlier decisions. (The adjustment factors are built from the action records, so this is checked directly, not assumed from the bar filter.)
   Also: the cutoff snapshot and the later freeze as two events (a `PENDING` batch cannot gain a member); requests outside the permitted range rejected by the capability; the D3 measurements of section 8.1 on worked paper records (round trips with scaling and partial exits, a split inside a trip, a missed signal counted as strategy-side).
   Separately, a pilot that measures time and **peak memory (operating-system peak RSS over a complete candidate evaluation, with the production configuration, recorded with machine and versions)**, then the calibration job (with the drift diagnostic at Sharpes 0, -0.5 and -1.0 and its fixed failure rule, c = 567) (the seven series of section 2.2, the D8 number of datasets each, the final procedure, the 7 decision checks at 0.1667% against the exact binomial boundary and the 14 diagnostic checks at 5% and 1% with exact p-values, measured rates with their bounds), the primary-test power and the full-policy pass probability; the reports are committed under `docs/` and section 2.1 gets both figures beside the theoretical table.
6. UI: batch history and the "previously tested candidates" count, with the two warnings; confirmation screen before freezing.
7. Policy: this file is the policy; `vti-alignment.md` section 3 gets a pointer to it.

**Batch 1 does not run until** the calibration report has passed and the primary-test power and full-policy pass probability are published, the statistical test, access restrictions and the slot accounting have passed their tests, and `make check` is green on the commit that runs it.

## Amendments (dated; the text above is frozen except as recorded here)

- **2026-11-16, clarification (Section 7, owner review).** The point-in-time contract now separates `known_at` (the frozen source-data snapshot) from the per-decision availability cutoff (`as_of`), and requires the capability to keep both, with tests that later-announced actions, memberships and restatements cannot affect earlier decisions or adjusted prices. No statistical rule changed; the reader already applies `as_of`, and this records that the evaluator must not lose it.
- **2026-11-16, addition (Section 7, owner review).** Added the rule for inputs whose availability time cannot be established: they cannot be treated as point-in-time evidence and make the dependent candidate `INSUFFICIENT_EVIDENCE`. Added that announcement/publication time and effective date are used separately, and that later price corrections must not reach earlier decisions. The per-input list of availability timestamps becomes part of the step-0 audit. No statistical rule changed.
- **2026-11-17, implementation notes (no statistical rule changed).** (1) The bootstrap and its calibration runner are built (`mc_bootstrap.py`, `mc_calibration.py`, `scripts/holdout_calibration.py`); measured cost is 0.34 s per dataset at B = 20,000, about 292 core-hours for the full calibration (about 24 hours on 12 cores), see `docs/holdout-pilot-2026-11-17.md`. The calibration has not been run. (2) The section 7 capability is an application-level table allow-list (`holdout_guard.py`): the evaluator receives a `GuardedConnection`, created only after the first-read marker, that answers reads over source and study-record tables and refuses everything else; the date window and per-decision `as_of` remain the job of the point-in-time readers, not of the guard. (3) A session-coverage check uses the distinct trading dates of the source bars as the calendar of the window. (4) Study runs now end with an automatic cutoff check in the worker; the cutoff records a snapshot only. (5) Backtest runs and strategy signals reaching past 2024-12-31 are hidden from research routes, failing closed when the lock is not anchored.
