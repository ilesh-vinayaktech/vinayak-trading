# Alpha discovery (plan.md phase 2): what is built and what it does not claim

Written 2026-11-15 from the code. Package `algo/alpha`, table `alpha_hypothesis` (migration 078), command `scripts/discover_alpha.py`.

## What it does

For every feature whose status is USABLE and every horizon asked for (default 1, 5, 20 and 60 sessions), on one data freeze:

1. **Forward return.** A feature known at the close of session *t* is acted on no earlier than session *t+1*, so the return runs from the close of
   *t+1* to the close of *t+1+h*. Using *t*'s own close would credit the feature with a move it could not have traded.
2. **Daily rank IC.** The Spearman rank correlation, across the stocks that day, between the feature and that forward return. Days with fewer than
   `--min-names` stocks (default 20) are skipped, never padded.
3. **A test of the mean IC.** Returns over *h* sessions overlap from one day to the next, so the daily ICs are autocorrelated; the standard error uses a
   Newey-West (Bartlett) long-run variance with lag *h − 1*. Without it the test would claim far more certainty than the data holds.
4. **Multiple-testing correction across all history.** The p-value is multiplied by the number of tests ever run (this batch and every earlier one), capped at 1.
   The more we look, the more evidence the next candidate needs. Failed hypotheses stay on the books for exactly this reason.
5. **A record.** Each result is written to `alpha_hypothesis` (insert-only) as CANDIDATE or REJECTED with its evidence: sample days, average stocks per day, mean IC,
   its spread, ICIR, hit rate, t-statistic, p-value, the adjusted p-value, the number of tests ever run, the direction and a hash of the discovery result.

A CANDIDATE needs both an adjusted p-value below 0.05 and a mean rank IC of at least 0.02 in size (a tiny effect can be "significant" over enough days
and still be worthless after costs). A stable negative IC is a candidate too; it would be used inverted.

## What it does not claim

- **CANDIDATE means "worth validating", never "works".** Validation (walk-forward, costs, the one holdout batch) is a separate, later gate.
- **The universe is the freeze's instruments, not point-in-time Nifty 200 membership.** Every record says so (`evidence.context`). Nothing found is evidence about
  the Nifty 200 until membership is strict-eligible (`docs/vti-alignment.md` §4).
- **Only development days are read.** The guarded reader cannot return a holdout day, an observation whose return would end after the development end is dropped,
  and the dataset hash covers every bar, so a quietly altered price makes the stored features unreadable instead of silently changing a result.
- **Price and volume features only.** Fundamental features are not registered as usable (`docs/vti-phase1-spec.md`). There is no machine learning here:
  the dependencies for it (XGBoost, scikit-learn) are not installed, and plan.md says to add each only when a phase needs it.

## How it is tested

Pure statistics and the engine are tested by hand-worked numbers (a Newey-West error worked by hand for lags 1 and 2), a planted signal that must be found
with the right sign and noise that must not, a property that prices after the last allowed day cannot change a result, and mutation testing (stats 94.8%,
discover 99.1%; the survivors are equivalent mutants). The registry and the runner are tested on a stored synthetic market, which is a random walk, so the right
answer is "nothing found" and the registry says so.
