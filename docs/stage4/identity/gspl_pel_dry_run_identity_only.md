# GSPL / PEL identity application: DRY RUN (rolled back; nothing written) - identity only

Config `config/identity_applications/gspl_pel.json` sha256 `7cf28cdd9403200150ca3ad454f1ce96e34952f3687b41ec9c1e0d08e6152efd`. Persisted right now: {'instrument': 2649, 'instrument_alias': 3098, 'corporate_action_relationship': 1, 'bar_1d': 3189203, 'partition_load': 2922, 'index_release_row': 146462, 'index_monthly_constituent': 45590}.

## Records that change (inside the transaction)

| table | before | after |
|---|---|---|
| instrument | 2649 | 2651 |
| instrument_alias | 3098 | 3100 |
| corporate_action_relationship | 1 | 3 |

Press-release rows re-mapped: **566**; monthly constituents re-mapped: **417**. Unmapped before [release rows, monthly]: {'GSPL': [210, 176], 'PEL': [379, 241]}.

### New instrument / alias / relationship rows

- instrument ['2656', 'GSPL', 'INE246F01010', 'Gujarat State Petronet Limited', 'delisted', 'None', 'None', '2006-02-16', '2026-05-11', '1']
- instrument ['2657', 'PEL', 'INE140A01024', 'Piramal Enterprises Limited', 'delisted', 'None', 'None', '2012-09-21', '2025-09-22', '1']
- alias ['2656', 'nse', 'GSPL', '2006-02-16', 'FIRST_OBSERVED', '2026-05-12', 'LAST_OBSERVED']
- alias ['2657', 'nse', 'PEL', '2012-09-21', 'FIRST_OBSERVED', '2025-09-23', 'LAST_OBSERVED']
- relationship ['4', 'AMALGAMATED_INTO', '2656', '907', 'GUJENERGY', '2026-05-01', '2026-05-11', '10', '13', 'PROVISIONAL', '12']
- relationship ['5', 'MERGED_INTO', '2657', '1761', 'PIRAMALFIN', '2025-09-16', '2025-09-22', 'None', 'None', 'PROVISIONAL', '16']

### Press-release rows for these symbols after [symbol, component, action, mapping, rows, first, last]

- ['GSPL', 'MIDCAP_100', 'EXCLUDED', 'MAPPED', '7', '2023-03-31', '2023-03-31']
- ['GSPL', 'NIFTY_200', 'EXCLUDED', 'MAPPED', '7', '2023-03-31', '2023-03-31']
- ['GSPL', 'None', 'EXCLUDED', 'MAPPED', '138', '2023-03-31', '2026-05-12']
- ['GSPL', 'None', 'EXCLUDED', 'UNMAPPED_SYMBOL', '2', 'None', 'None']
- ['GSPL', 'None', 'INCLUDED', 'MAPPED', '56', '2020-06-26', '2024-12-31']
- ['PEL', 'MIDCAP_100', 'EXCLUDED', 'MAPPED', '3', '2024-09-30', '2024-09-30']
- ['PEL', 'MIDCAP_100', 'INCLUDED', 'MAPPED', '7', '2023-03-31', '2023-03-31']
- ['PEL', 'MIDCAP_100_FREE_FLOAT', 'EXCLUDED', 'MAPPED', '7', '2017-03-31', '2017-03-31']
- ['PEL', 'NIFTY_100', 'EXCLUDED', 'MAPPED', '7', '2022-08-08', '2022-08-08']
- ['PEL', 'NIFTY_200', 'EXCLUDED', 'MAPPED', '10', '2022-08-08', '2024-09-30']
- ['PEL', 'NIFTY_200', 'INCLUDED', 'MAPPED', '7', '2023-03-31', '2023-03-31']
- ['PEL', 'NIFTY_NEXT_50', 'EXCLUDED', 'MAPPED', '7', '2022-08-08', '2022-08-08']
- ['PEL', 'None', 'EXCLUDED', 'MAPPED', '191', '2018-04-02', '2025-09-23']
- ['PEL', 'None', 'EXCLUDED', 'UNMAPPED_SYMBOL', '21', '2025-09-30', '2025-09-30']
- ['PEL', 'None', 'INCLUDED', 'MAPPED', '119', '2018-12-28', '2024-09-30']

### Monthly constituents after [symbol, index, mapping, rows, first, last]

- ['GSPL', 'NIFTY 200', 'MAPPED', '63', '2017-07-31', '2022-03-31']
- ['GSPL', 'NIFTY Free Float Midcap 100', 'MAPPED', '14', '2017-07-31', '2018-03-28']
- ['GSPL', 'NIFTY Full Midcap 100', 'MAPPED', '14', '2017-07-31', '2018-03-28']
- ['GSPL', 'NIFTY Midcap 100', 'MAPPED', '49', '2018-04-30', '2022-03-31']
- ['GSPL', 'Nifty 200', 'MAPPED', '16', '2017-01-31', '2017-10-31']
- ['GSPL', 'Nifty Free Float Midcap 100', 'MAPPED', '4', '2017-08-31', '2017-10-31']
- ['GSPL', 'Nifty Full Midcap 100', 'MAPPED', '4', '2017-08-31', '2017-10-31']
- ['GSPL', 'Nifty Midcap 100', 'MAPPED', '12', '2017-01-31', '2017-06-30']
- ['PEL', 'NIFTY 100', 'MAPPED', '63', '2017-07-31', '2022-03-31']
- ['PEL', 'NIFTY 200', 'MAPPED', '63', '2017-07-31', '2022-03-31']
- ['PEL', 'NIFTY Next 50', 'MAPPED', '63', '2017-07-31', '2022-03-31']
- ['PEL', 'Nifty 100', 'MAPPED', '16', '2017-01-31', '2017-10-31']
- ['PEL', 'Nifty 200', 'MAPPED', '16', '2017-01-31', '2017-10-31']
- ['PEL', 'Nifty Midcap 100', 'MAPPED', '4', '2017-01-31', '2017-02-28']
- ['PEL', 'Nifty Next 50', 'MAPPED', '16', '2017-01-31', '2017-10-31']

### Bars after [symbol, rows, first, last]

- none (identity-only stage)

## Fingerprints outside the intended set: before vs after

| record set | before (rows, hash) | after | unchanged |
|---|---|---|---|
| instrument | 2649, fddd055f76 | 2649, fddd055f76 | yes |
| instrument_alias | 3098, 1699d6b964 | 3098, 1699d6b964 | yes |
| corporate_action_relationship | 1, 1a926fa4d8 | 1, 1a926fa4d8 | yes |
| security_conversion | 1, 66bbaaf1e2 | 1, 66bbaaf1e2 | yes |
| corporate_action | 4823, f543efe822 | 4823, f543efe822 | yes |
| action_resolution | 53, 09cb17266d | 53, 09cb17266d | yes |
| bar_1d (other instruments) | 3189203, 5f9353a164 | 3189203, 5f9353a164 | yes |
| index_release_row (other symbols) | 145873, 779f244e79 | 145873, 779f244e79 | yes |
| index_monthly_constituent (other symbols) | 45173, e7ca4b7c10 | 45173, e7ca4b7c10 | yes |
| index_snapshot | 600, 5236cd7ec6 | 600, 5236cd7ec6 | yes |
| review_decision | 28, 3dc189e167 | 28, 3dc189e167 | yes |
| look-alikes GNRL / GUJENERGY / PIRAMALFIN (instrument + alias + bars) | 2157, ead7cea55f | 2157, ead7cea55f | yes |

