# BHARATFIN / HEXAWARE identity application: DRY RUN (rolled back; nothing written) - identity only

Config `config/identity_applications/bharatfin_hexaware.json` sha256 `0b05256e88d1fc9d1f4245cd5eb8ec59a4075bc408b912aee41f6e0207face0b`. Persisted right now: {'instrument': 2654, 'instrument_alias': 3103, 'corporate_action_relationship': 1, 'bar_1d': 7570830, 'partition_load': 2933, 'index_release_row': 146462, 'index_monthly_constituent': 45590}.

## Records that change (inside the transaction)

| table | before | after |
|---|---|---|
| instrument | 2654 | 2656 |
| instrument_alias | 3103 | 3105 |
| corporate_action_relationship | 1 | 2 |

Press-release rows re-mapped: **218**; monthly constituents re-mapped: **202**. Unmapped before [release rows, monthly]: {'BHARATFIN': [89, 94], 'HEXAWARE': [129, 108]}.

### New instrument / alias / relationship rows

- instrument ['2667', 'BHARATFIN', 'INE180K01011', 'Bharat Financial Inclusion Limited', 'delisted', 'None', 'None', '2016-07-01', '2019-07-02', '1']
- instrument ['2668', 'HEXAWARE', 'INE093A01033', 'Hexaware Technologies Limited', 'delisted', 'None', '2020-11-09', '2002-06-14', '2020-10-30', '1']
- alias ['2667', 'nse', 'BHARATFIN', '2016-07-01', 'FIRST_OBSERVED', '2019-07-03', 'LAST_OBSERVED']
- alias ['2668', 'nse', 'HEXAWARE', '2002-06-14', 'FIRST_OBSERVED', '2020-10-31', 'LAST_OBSERVED']
- relationship ['10', 'AMALGAMATED_INTO', '2667', '1078', 'INDUSINDBK', '2019-07-04', '2019-07-02', '639', '1000', 'PROVISIONAL', '2']

### Press-release rows for these symbols after [symbol, component, action, mapping, rows, first, last]

- ['BHARATFIN', 'MIDCAP_100', 'EXCLUDED', 'MAPPED', '7', '2018-12-28', '2018-12-28']
- ['BHARATFIN', 'NIFTY_200', 'EXCLUDED', 'MAPPED', '7', '2018-12-28', '2018-12-28']
- ['BHARATFIN', 'None', 'EXCLUDED', 'MAPPED', '56', '2017-05-26', '2018-12-28']
- ['BHARATFIN', 'None', 'INCLUDED', 'MAPPED', '19', '2017-04-17', '2018-06-29']
- ['HEXAWARE', 'MIDCAP_100', 'EXCLUDED', 'MAPPED', '3', '2020-09-25', '2020-09-25']
- ['HEXAWARE', 'NIFTY_200', 'EXCLUDED', 'MAPPED', '3', '2020-09-25', '2020-09-25']
- ['HEXAWARE', 'None', 'EXCLUDED', 'MAPPED', '74', '2017-03-31', '2020-09-25']
- ['HEXAWARE', 'None', 'INCLUDED', 'MAPPED', '49', '2017-03-31', '2020-06-26']

### Monthly constituents after [symbol, index, mapping, rows, first, last]

- ['BHARATFIN', 'NIFTY 200', 'MAPPED', '22', '2017-07-31', '2018-11-30']
- ['BHARATFIN', 'NIFTY Free Float Midcap 100', 'MAPPED', '14', '2017-07-31', '2018-03-28']
- ['BHARATFIN', 'NIFTY Full Midcap 100', 'MAPPED', '14', '2017-07-31', '2018-03-28']
- ['BHARATFIN', 'NIFTY Midcap 100', 'MAPPED', '8', '2018-04-30', '2018-11-30']
- ['BHARATFIN', 'Nifty 200', 'MAPPED', '16', '2017-01-31', '2017-10-31']
- ['BHARATFIN', 'Nifty Free Float Midcap 100', 'MAPPED', '4', '2017-08-31', '2017-10-31']
- ['BHARATFIN', 'Nifty Full Midcap 100', 'MAPPED', '4', '2017-08-31', '2017-10-31']
- ['BHARATFIN', 'Nifty Midcap 100', 'MAPPED', '12', '2017-01-31', '2017-06-30']
- ['HEXAWARE', 'NIFTY 200', 'MAPPED', '44', '2017-07-31', '2020-08-31']
- ['HEXAWARE', 'NIFTY Full Midcap 100', 'MAPPED', '14', '2017-07-31', '2018-03-28']
- ['HEXAWARE', 'NIFTY Midcap 100', 'MAPPED', '30', '2018-04-30', '2020-08-31']
- ['HEXAWARE', 'Nifty 200', 'MAPPED', '16', '2017-01-31', '2017-10-31']
- ['HEXAWARE', 'Nifty Full Midcap 100', 'MAPPED', '4', '2017-08-31', '2017-10-31']

### Bars after [symbol, rows, first, last]

- none (identity-only stage)

## Fingerprints outside the intended set: before vs after

| record set | before (rows, hash) | after | unchanged |
|---|---|---|---|
| instrument | 2654, dd74583142 | 2654, dd74583142 | yes |
| instrument_alias | 3103, 1e9b9db8f2 | 3103, 1e9b9db8f2 | yes |
| corporate_action_relationship | 1, 1a926fa4d8 | 1, 1a926fa4d8 | yes |
| security_conversion | 1, 66bbaaf1e2 | 1, 66bbaaf1e2 | yes |
| corporate_action | 24852, 7752c9dd31 | 24852, 7752c9dd31 | yes |
| action_resolution | 2824, e698d3a304 | 2824, e698d3a304 | yes |
| bar_1d (other instruments) | 7570830, 487fd76050 | 7570830, 487fd76050 | yes |
| index_release_row (other symbols) | 146244, ecbd4043c4 | 146244, ecbd4043c4 | yes |
| index_monthly_constituent (other symbols) | 45388, bacd7b46d2 | 45388, bacd7b46d2 | yes |
| index_snapshot | 800, cb5b40bd09 | 800, cb5b40bd09 | yes |
| review_decision | 28, 3dc189e167 | 28, 3dc189e167 | yes |
| look-alikes GNRL / GUJENERGY / PIRAMALFIN (instrument + alias + bars) | 4748, 7739f7f520 | 4748, 7739f7f520 | yes |

