# Strategy factory (plan.md phase 3): what is built and what is not

Written 2026-11-15 from the code. Package `algo/factory` (`dsl`, `interpreter`, `registry`), table `strategy_definition` (migration 079).

## Built

**A typed strategy language (`dsl.py`).** A definition is a JSON object: entry and exit condition groups (`all` or `any`) over features that exist in the feature
registry, a ranking feature, `max_positions` and a sizing rule (`EQUAL_WEIGHT` or `INVERSE_VOLATILITY`), a position cap, and a rebalance cadence (`DAILY`,
`WEEKLY`, `MONTHLY`). It is validated when it is parsed: an unknown feature, a non-number threshold (a boolean, NaN, infinity, text), an unknown operator or a
shape outside the allowed ones is refused with a message, never accepted and ignored. Its hash is the same whatever the key order or number spelling.
Nothing in a definition is code, so no model has to be trusted to write Python.

**An interpreter (`interpreter.py`).** `DslStrategy` runs a definition as an ordinary `Strategy`, so the existing backtest engine, risk engine and paper runner
treat it like any other. Rules are fixed and written at the top of the module: a stock is READY only with a bar today and a value for every feature it reads;
a stock short of history is reported as warming up, never silently dropped; more than 5% of members with no bar is an explicit `DataNotReady`; held stocks are
sold only on the exit condition, on leaving the universe, or when over the limit; entries take the best-ranked qualifiers (ties: lower instrument id); in strict
mode a day whose membership evidence is unusable makes no decision. It evaluates the registered feature functions themselves, on the bars `Context` serves.

**Immutable versions (`registry.py`).** Every version is an insert-only row naming its parent, the author and the reason. Versions are 1, 2, 3 with no gaps, a new
version must change a rule (not just the description), and what is read back is checked against its stored hash, so an altered row is refused. The table has no
status column: a definition cannot be marked usable, so it cannot bypass validation.

## Not built (and not claimed)

- **No factory that generates definitions.** Turning a CANDIDATE alpha hypothesis into a definition needs thresholds, and the language has no percentile operators yet;
  inventing thresholds from the development data would be an overfitting step that deserves its own design.
- **No experiment orchestrator, parameter optimisation, feature-combination search or experiment comparison.** The existing study framework does grids for coded
  strategies; a DSL strategy cannot yet be registered as a study (studies look strategies up by id in a fixed table).
- **No connection to validation or promotion.** A definition can be backtested by hand through the engine, as the integration test does. Whether a version may go to
  paper or live is decided by the existing validation and lifecycle gates, which nothing here touches or bypasses.
- **Language limits (version 1):** long-only, daily, price and volume features only. Features whose value depends on all history (the ATR family) are refused. No
  stop-loss, holding period, sector or fundamental conditions, and no execution timing: saying so is better than accepting words the engine would ignore.

## Tests

Hand-worked decisions (entries, exits, caps, inverse-volatility weights, every operator, ties, warm-up, missing bars), the real backtest engine running a definition
on the synthetic market (deterministic to the bit, one decision per ISO week, falling stocks never bought, strict-mode skipping), and the registry on a real database.
Mutation testing of the language and the interpreter: the survivors are equivalent mutants.
