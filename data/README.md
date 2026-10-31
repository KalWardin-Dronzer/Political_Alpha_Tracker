# Data

Every input the results depend on is committed here, except the price panel,
which comes from Yahoo Finance and is downloaded with `python cli.py prices`.

| File | What it is | Where it came from |
|---|---|---|
| `PurchaseData.csv` | 18,871 electoral bonds: date, purchaser name, denomination. Rs 12,155.5 crore bought by 1,316 purchaser names between 12 April 2019 and 11 January 2024 (336 blank rows are skipped). | The purchase data SBI disclosed and the Election Commission of India published in March 2024. It names buyers only; it has no bond numbers that would link a purchase to the party that redeemed it. |
| `companies.csv` | 1,589 listed securities: scrip code, NSE symbol, name, ISIN, CIN, sector, industry. 1,472 have a CIN; 123 have a sector. | Snapshot of an earlier version's company store. The universe is NSE's equity list mapped to BSE scrip codes. CINs came from the Zaubacorp resolver in `src/data/cin_resolver.py`; sectors came from NSE's sector classification. |
| `donor_cins.csv` | 29 purchaser spellings mapped to the CIN of the listed company they name. | An earlier entity-resolution step, checked by hand. It covers names the strict name match misses, such as "DIVI S LABORATORIES" and "JINDAL STEEL AND POWER" (since renamed Jindal Steel). |
| `nse_delisted.parquet` | 416 NSE delistings with date and type. | NSE's delisted-securities list. Used to estimate survivorship bias. |
| `backtest_trials.jsonl` | Every factor-backtest configuration ever run. | Appended by the backtests. The deflated Sharpe ratio is computed against this count, so do not prune it. |
| `prices/` (not committed) | Adjusted daily closes and volumes. | Yahoo Finance via yfinance. The committed results used the panel downloaded on 10 September 2026: 1,905 trading days from 1 January 2019, 1,588 symbols. A fresh download covers more days, so its numbers will differ slightly. |

## Known limits

- Sector labels exist for 123 of the 1,589 companies. The lead-lag test needs
  them, so it can only use sectors with enough connected companies and peers.
- 117 companies have no CIN. They are keyed by scrip code, so a CIN-based
  donor mapping cannot reach them; the name match still can.
