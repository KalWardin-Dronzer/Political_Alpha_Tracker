"""Tests for loading the SBI electoral bond purchase disclosure."""

from src.data.bonds import load_bond_purchases


def test_parses_rows_and_skips_blank_ones(tmp_path):
    csv = tmp_path / "PurchaseData.csv"
    csv.write_text(
        "﻿Date of Purchase,Purchaser Name,Denomination\n"
        "12-Apr-19,  A B C INDIA LIMITED ,100000\n"
        ",,\n"
        "03-Oct-23,XYZ LTD,\"1,00,00,000\"\n",
        encoding="utf-8")
    bonds = load_bond_purchases(csv)
    assert list(bonds["purchaser"]) == ["A B C INDIA LIMITED", "XYZ LTD"]
    assert list(bonds["amount"]) == [100_000, 10_000_000]
    assert list(bonds["year"]) == [2019, 2023]


def test_committed_disclosure_loads_completely():
    """The committed file: 18,871 bonds worth Rs 12,155.5 crore, April 2019 to January 2024."""
    bonds = load_bond_purchases()
    assert len(bonds) == 18_871
    assert bonds["amount"].sum() == 121_555_132_000
    assert bonds["purchaser"].nunique() == 1_316
    assert set(bonds["amount"]) == {1_000, 10_000, 100_000, 1_000_000, 10_000_000}
    assert bonds["date"].notna().all()
    assert str(bonds["date"].min().date()) == "2019-04-12"
    assert str(bonds["date"].max().date()) == "2024-01-11"
