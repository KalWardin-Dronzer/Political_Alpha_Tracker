"""
Rebuild data/companies.csv, the listed-company universe, from committed raw inputs.

    python cli.py companies

Inputs (all in data/, see data/README.md):

- nse_equity_list.csv: NSE's list of equities (EQUITY_L.csv), downloaded
  9 November 2026. It defines the universe: 2,645 equities.
- nifty_total_market.csv: constituents of the Nifty Total Market index on the
  same day, with NSE's industry classification. It supplies sector labels.
- company_ids.csv: ISIN, NSE symbol, CIN and BSE scrip code of the 1,589
  companies in the earlier universe. Those companies keep their old key, so
  earlier results stay comparable; the rest are keyed by ISIN. They are matched
  by ISIN, else by symbol: seven have since changed ISIN.
- sectors_earlier.csv: the earlier universe's 123 NSE sector labels, with two
  names normalised ("IT", "Oil & Gas"). They agree with the index file on all
  93 companies both cover, so they label the 30 that the index file does not.

The earlier universe kept only the equities whose NSE symbol mapped to a BSE
scrip code, and so dropped 40% of NSE's list, Tech Mahindra and Zydus
Lifesciences among them.
"""

import pandas as pd

from src.config import COMPANIES_FILE, DATA_DIR

EQUITY_LIST_FILE = DATA_DIR / "nse_equity_list.csv"
TOTAL_MARKET_FILE = DATA_DIR / "nifty_total_market.csv"
COMPANY_IDS_FILE = DATA_DIR / "company_ids.csv"
EARLIER_SECTORS_FILE = DATA_DIR / "sectors_earlier.csv"

# NSE Indices' industry classification structure (March 2022): each of the 22
# sectors in the index files belongs to one of 12 macro-economic sectors.
# Source: nsearchives.nseindia.com, "NSE Indices_Industry Classification
# Structure-2022-03.pdf" (codes IN01 to IN12).
MACRO_SECTOR = {
    "Chemicals": "Commodities",
    "Construction Materials": "Commodities",
    "Metals & Mining": "Commodities",
    "Forest Materials": "Commodities",
    "Automobile and Auto Components": "Consumer Discretionary",
    "Consumer Durables": "Consumer Discretionary",
    "Textiles": "Consumer Discretionary",
    "Media Entertainment & Publication": "Consumer Discretionary",
    "Realty": "Consumer Discretionary",
    "Consumer Services": "Consumer Discretionary",
    "Oil Gas & Consumable Fuels": "Energy",
    "Fast Moving Consumer Goods": "Fast Moving Consumer Goods",
    "Financial Services": "Financial Services",
    "Healthcare": "Healthcare",
    "Construction": "Industrials",
    "Capital Goods": "Industrials",
    "Information Technology": "Information Technology",
    "Services": "Services",
    "Telecommunication": "Telecommunication",
    "Power": "Utilities",
    "Utilities": "Utilities",
    "Diversified": "Diversified",
}

COLUMNS = ["scrip_code", "nse_symbol", "name", "isin", "cin", "sector", "industry", "listed"]


def _read(path) -> pd.DataFrame:
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    table.columns = [c.strip() for c in table.columns]
    return table.apply(lambda col: col.str.strip())


def _lookup(universe: pd.DataFrame, table: pd.DataFrame, column: str) -> pd.Series:
    """`column` of `table` for each company, matched by ISIN, else by NSE symbol."""
    by_isin = universe["isin"].map(table.drop_duplicates("isin").set_index("isin")[column])
    by_symbol = universe["nse_symbol"].map(table.drop_duplicates("nse_symbol").set_index("nse_symbol")[column])
    return by_isin.fillna(by_symbol).fillna("")


def build() -> pd.DataFrame:
    """The universe: every equity on NSE's list, with sector labels where NSE publishes one."""
    nse = _read(EQUITY_LIST_FILE)
    total_market = _read(TOTAL_MARKET_FILE)
    ids = _read(COMPANY_IDS_FILE)
    earlier = _read(EARLIER_SECTORS_FILE)

    unknown = sorted(set(total_market["Industry"]) - set(MACRO_SECTOR))
    if unknown:
        raise ValueError(f"industries missing from MACRO_SECTOR: {unknown}")
    industry = dict(zip(total_market["ISIN Code"], total_market["Industry"]))

    universe = pd.DataFrame({
        "nse_symbol": nse["SYMBOL"],
        "name": nse["NAME OF COMPANY"],
        "isin": nse["ISIN NUMBER"],
        "listed": pd.to_datetime(nse["DATE OF LISTING"], format="%d-%b-%Y").dt.strftime("%Y-%m-%d"),
    }).drop_duplicates("isin")
    universe["cin"] = _lookup(universe, ids, "cin")
    universe["scrip_code"] = _lookup(universe, ids, "scrip_code")
    universe["industry"] = universe["isin"].map(industry).fillna("")
    universe["sector"] = universe["industry"].map(MACRO_SECTOR).fillna("")
    unlabelled = universe["sector"] == ""
    universe.loc[unlabelled, "sector"] = _lookup(universe, earlier, "sector")[unlabelled]
    universe.loc[unlabelled, "industry"] = _lookup(universe, earlier, "industry")[unlabelled]
    return universe.sort_values("nse_symbol").reset_index(drop=True)[COLUMNS]


def main() -> int:
    universe = build()
    universe.to_csv(COMPANIES_FILE, index=False)
    labelled = (universe["sector"] != "").sum()
    print(f"wrote {COMPANIES_FILE.name}: {len(universe):,} companies, {labelled:,} with a sector label")
    return 0
