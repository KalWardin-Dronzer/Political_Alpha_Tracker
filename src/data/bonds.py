"""
Electoral bond purchases, from the SBI disclosure the Election Commission of
India published in March 2024.

PurchaseData.csv has one row per bond: date of purchase, purchaser name and
denomination. It records who bought bonds, not which party redeemed them, and
carries no bond numbers that could link the two.
"""

import pandas as pd

from src.config import BOND_PURCHASES_FILE


def load_bond_purchases(path=BOND_PURCHASES_FILE) -> pd.DataFrame:
    """One row per bond: purchaser, amount in rupees, purchase date and year."""
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    bonds = pd.DataFrame({
        "purchaser": raw["Purchaser Name"].str.strip(),
        "amount": pd.to_numeric(
            raw["Denomination"].str.replace(r"[^\d.]", "", regex=True), errors="coerce"),
        "date": pd.to_datetime(
            raw["Date of Purchase"].str.strip(), format="%d-%b-%y", errors="coerce"),
    })
    bonds = bonds[(bonds["purchaser"] != "") & (bonds["amount"] > 0)].reset_index(drop=True)
    bonds["year"] = bonds["date"].dt.year.astype("Int64")
    return bonds
