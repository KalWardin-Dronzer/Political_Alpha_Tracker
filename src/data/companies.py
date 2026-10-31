"""
The listed-company universe and the donor-to-CIN table, both committed
snapshots. data/README.md describes how each was built.
"""

import pandas as pd

from src.config import COMPANIES_FILE, DONOR_CINS_FILE


def load_companies(path=COMPANIES_FILE) -> pd.DataFrame:
    """One row per listed security: scrip code, NSE symbol, name, ISIN, CIN, sector, industry."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_donor_cins(path=DONOR_CINS_FILE) -> dict[str, str]:
    """Purchaser spelling -> CIN of the listed company it names."""
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    return dict(zip(table["donor_name"], table["cin"]))


def company_key(company) -> str:
    """A company's identity: its CIN, or its scrip code when it has none.

    Share classes listed separately under one CIN are one company.
    """
    return company["cin"] or company["scrip_code"]
