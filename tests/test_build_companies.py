"""
Tests for the universe builder: it must reproduce the committed companies.csv
from the committed raw files, cover every NSE industry, and keep the earlier
universe's keys so earlier results stay comparable.
"""

import pandas as pd

from src.config import COMPANIES_FILE
from src.data.build_companies import (COMPANY_IDS_FILE, EQUITY_LIST_FILE, MACRO_SECTOR, TOTAL_MARKET_FILE,
                                      _read, build)
from src.data.companies import company_key


def test_every_industry_in_the_index_file_has_a_macro_sector():
    industries = set(_read(TOTAL_MARKET_FILE)["Industry"])
    assert industries <= set(MACRO_SECTOR)
    assert len(set(MACRO_SECTOR.values())) == 12   # NSE's 12 macro-economic sectors


def test_the_committed_universe_is_what_the_builder_makes():
    committed = pd.read_csv(COMPANIES_FILE, dtype=str, keep_default_na=False)
    assert committed.equals(build().astype(str))


def test_the_universe_is_nse_list_and_keys_are_unique_per_listing():
    universe = build()
    assert set(universe["isin"]) == set(_read(EQUITY_LIST_FILE)["ISIN NUMBER"])
    keys = universe.apply(company_key, axis=1)
    assert (keys != "").all()
    # Only share classes of one company (same CIN) may share a key.
    shared = universe[keys.duplicated(keep=False)]
    assert shared["cin"].nunique() <= shared.groupby("cin").ngroups and (shared["cin"] != "").all()


def test_earlier_companies_keep_their_keys():
    """Matched by ISIN, else by symbol: some have since changed symbol (HEG is now HEGAM), others ISIN."""
    ids = _read(COMPANY_IDS_FILE)
    universe = build()
    by_isin = universe.set_index("isin")["cin"]
    by_symbol = universe.drop_duplicates("nse_symbol").set_index("nse_symbol")["cin"]
    found = ids["isin"].map(by_isin).fillna(ids["nse_symbol"].map(by_symbol))
    assert found.notna().all()
    assert (found == ids["cin"]).all()
