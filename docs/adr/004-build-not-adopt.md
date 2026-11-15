# ADR-004: Build the backtest/OMS/paper stack in this repository; do not adopt NautilusTrader

**Status.** Accepted as built, 2026-11-15. This records the decision the code already embodies. The one-week NautilusTrader spike that `TODO.md` S2 called for was
NOT performed, so the comparison below is reasoned from this project's requirements, not measured against that framework. Reopen it if a requirement here changes.

**Context.** What this system must do that a general trading framework does not do for us:

1. **Point-in-time everything.** Readers pinned to a `known_at`, corporate-action resolutions with evidence classes and provisional/verified status, membership with
   announcement versus effective dates, filings by broadcast time. These live in the data layer and are enforced in tests (look-ahead harness, holdout lock).
2. **A research-governance layer.** A global holdout lock, one holdout batch, research families and trial counts, dataset and study hashes, verdict states. None of
   this exists in a trading framework; it is the product.
3. **Indian cash-equity costs as dated, evidenced data** (STT, exchange, SEBI, GST, stamp, DP charges once per scrip per day) with an evidence state per component.
4. **A strategy boundary we control.** Strategies see data only through `Context`, run in a sandboxed process, and cannot reach the broker, database or network.
5. **One engine for backtest and paper.** `tests/integration/paper/test_parity.py` shows the engine and the paper runner decide identically on the same bars.

**Decision.** Keep the engine, the event-sourced OMS, the risk engine, the paper path and the Kite adapter in this repository. Use libraries for what is generic
(psycopg, pydantic, FastAPI, hypothesis), not a trading framework.

**Consequences.** Full control of semantics that matter for correctness (adjustment, knowledge time, costs), at the price of building and testing the engine
ourselves (hence the 90% branch gate and 100% floors on the money paths, and a pinned golden backtest). No live tick-level or multi-venue support, which is not needed.

**Revisit when** intraday or derivatives trading becomes a goal (where a mature matching and margin model is expensive to rebuild), or maintenance of the engine
costs more than the control is worth. The first step then is the spike this ADR skipped: one week, with the checklist in `TODO.md` S2.
