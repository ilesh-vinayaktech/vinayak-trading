# Benchmark Release 1.4 - change report against 1.3

Same datasets and evidence as 1.3. Two owner decisions of 2026-11-13:
1. U06 (net TRI gains on gross) and U08 (gross/net independence) are about the net series; they now apply to Nifty 50 net only, not Nifty 50 gross.
2. The benchmark gate is ON (`config/benchmark_gate.json`): a study's benchmark gates use only a benchmark that is BENCHMARK_GATE_ELIGIBLE in the latest release.

BENCHMARK_GATE_ELIGIBLE: Nifty 200 gross TRI, Nifty 50 gross TRI, Nifty 200 price return. Not eligible: Nifty 50 net (fails technical validation; U06, U08).
(Only a total-return series can back a gate in code: `benchmark.gate_returns` refuses price series, so the Nifty 200 price return is eligible but unusable for gates.)
Audit: `docs/benchmark-audit-1.4`.
