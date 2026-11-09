# NESTLEIND conversion check on real prices (read-only; hypothetical position in memory)

- old ISIN close on 2024-01-04: 27116.40; new ISIN close on 2024-01-05: 2666.40 (x10 = 26664.00)
- 100 old shares, cost 2711640.00 (average 27116.40) become 1000 new shares, cost 2711640.00 (average 2711.64)
- equity 10000000.00 on 2024-01-04 -> 9954760.00 on 2024-01-05: change -45240.00 = market move -45240.00

| check | result |
|---|---|
| a position was converted | True |
| quantity x10 | True |
| cost basis moved exactly | True |
| no cash movement | True |
| zero realised P&L and fees | True |
| wealth change across 4-5 Jan equals the market move exactly | True |
| unrealised P&L moved by the same amount | True |
| the ledger reconciles | True |

**Result: PASS**
