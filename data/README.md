# Data

Every input the results depend on is committed here, except the price panel,
which comes from Yahoo Finance and is downloaded with `python cli.py prices`.

| File | What it is | Where it came from |
|---|---|---|
| `PurchaseData.csv` | 18,871 electoral bonds: date, purchaser name, denomination. Rs 12,155.5 crore bought by 1,316 purchaser names between 12 April 2019 and 11 January 2024 (336 blank rows are skipped). | The purchase data SBI disclosed and the Election Commission of India published in March 2024. It names buyers only; it has no bond numbers that would link a purchase to the party that redeemed it. |
| `nse_equity_list.csv` | NSE's list of equities, 2,645 rows: symbol, name, series, listing date, ISIN. | `EQUITY_L.csv` from nsearchives.nseindia.com, downloaded 9 November 2026. It defines the universe. |
| `nifty_total_market.csv` | The 754 constituents of the Nifty Total Market index with NSE's industry classification (22 sectors). | `ind_niftytotalmarket_list.csv` from nsearchives.nseindia.com, downloaded 9 November 2026. It supplies sector labels, mapped to NSE's 12 macro-economic sectors by NSE's published classification structure (March 2022). |
| `company_ids.csv` | ISIN, NSE symbol, CIN and BSE scrip code of the 1,589 companies in the earlier universe. | The earlier universe's `companies.csv`. Those companies keep their old key (CIN, else scrip code), so earlier results stay comparable. CINs came from the Zaubacorp resolver in `src/data/cin_resolver.py`. |
| `sectors_earlier.csv` | The earlier universe's 123 sector labels, two names normalised ("IT" to "Information Technology", "Oil & Gas" to "Energy"). | NSE's sector classification, via the earlier company store. They agree with the index file on all 93 companies both cover, so they label the 30 small companies it does not. |
| `companies.csv` | The universe: 2,645 equities with NSE symbol, name, ISIN, CIN and scrip code where known, sector, industry and listing date. 779 have a sector label. | Built from the four files above by `python cli.py companies` (`src/data/build_companies.py`); a test checks the committed file is what the builder makes. |
| `donor_cins.csv` | 29 purchaser spellings mapped to the CIN of the listed company they name. | An earlier entity-resolution step, checked by hand. It covers names the strict name match misses, such as "DIVI S LABORATORIES" and "JINDAL STEEL AND POWER" (since renamed Jindal Steel). |
| `match_audit.csv` | A decision for every purchaser reviewed in November 2026: `same_company` (another spelling, a former name, or a company since merged into the listed one), `subsidiary` (majority owned by a listed company) or `not_attributed`, each with the listed company, the relation and a source. | The 60 largest purchasers the rules left unattributed and every unattributed name close to a listed company's under looser rules (`python -m scripts.audit_candidates` lists them, and shows none without a decision). Sources are company filings, rating agencies' rationales and news reports; "name" means the decision rests on the names alone. |
| `nse_delisted.parquet` | 416 NSE delistings with date and type. | NSE's delisted-securities list. Used to estimate survivorship bias. |
| `backtest_trials.jsonl` | Every factor-backtest configuration ever run. | Appended by the backtests. The deflated Sharpe ratio is computed against this count, so do not prune it. |
| `prices/` (not committed) | Adjusted daily closes and volumes. | Yahoo Finance via yfinance, to a pinned end date (`PRICE_END` in `src/config.py`): 1,905 trading days from 1 January 2019 to 10 September 2026. The earlier universe's 1,588 symbols were downloaded on 10 September 2026; the 1,003 added in November returned data for the same calendar. Four of those are earlier companies whose symbol has since changed (HEG is now HEGAM); their returns agree with the September download on every day both have. `python cli.py prices` fetches only symbols missing from the panel. |

## Known limits

- The earlier universe kept only equities whose NSE symbol mapped to a BSE scrip
  code, so it held 1,589 of NSE's 2,645 and missed companies such as Tech
  Mahindra and Zydus Lifesciences. It was rebuilt from NSE's full list in
  November 2026.
- Sector labels cover 779 companies: 749 of the index's 754 constituents (the
  other five are three REITs and two placeholder rows) and 30 smaller companies.
  The lead-lag test needs them, so it uses only labelled companies.
- Index membership is as of November 2026, so the labelled set leans towards
  companies that were large at the end of the sample.
- 58 equities in the universe have no prices: all listed after the panel's end
  date, between 15 September and 11 November 2026.
- The audit covers the largest unattributed purchasers and every close name; a
  small subsidiary with a name unlike its parent's, outside the top 60, would
  still be missed.
