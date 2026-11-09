"""
Tests for the price panel's cleaning and its point-in-time liquidity history.
"""

import numpy as np
import pandas as pd
import pytest

import src.data.price_store as price_store
from src.data.price_store import PriceStore, remove_impossible_moves

DAYS = pd.bdate_range("2024-01-01", periods=6)


def _panel(**columns) -> pd.DataFrame:
    return pd.DataFrame(columns, index=DAYS[:len(next(iter(columns.values())))], dtype=float)


def test_a_bad_print_that_reverts_leaves_no_trace():
    """CYBERTECH-style: +9,411% one day, back the next."""
    raw = _panel(X=[100, 101, 9600, 102, 103])
    clean, removed = remove_impossible_moves(raw)
    returns = clean["X"].pct_change(fill_method=None)
    assert returns.iloc[2] == pytest.approx(0.0) and returns.iloc[3] == pytest.approx(0.0)
    assert returns.iloc[1] == pytest.approx(0.01) and returns.iloc[4] == pytest.approx(1 / 102)
    assert len(removed) == 2
    assert clean["X"].iloc[-1] == 103   # the latest price is untouched


def test_an_unadjusted_split_is_rescaled_not_a_crash():
    raw = _panel(X=[100, 101, 50.5, 51])
    clean, removed = remove_impossible_moves(raw)
    assert list(clean["X"]) == pytest.approx([50, 50.5, 50.5, 51])
    assert removed.index.tolist() == [(DAYS[2], "X")]


def test_moves_within_the_limit_gaps_and_other_symbols_are_kept():
    raw = _panel(X=[100, 130, 100, 120], Y=[10, np.nan, np.nan, 30])
    clean, removed = remove_impossible_moves(raw, limit=0.4)
    assert clean["X"].tolist() == raw["X"].tolist()          # moves of 30% and -23% stay
    # Y's move is measured across the gap from the last close (+200%) and removed;
    # the missing days stay missing.
    assert clean["Y"].isna().tolist() == raw["Y"].isna().tolist()
    assert clean["Y"].iloc[0] == pytest.approx(30.0)
    assert removed.index.tolist() == [(DAYS[3], "Y")]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(price_store, "CLOSE_FILE", tmp_path / "close.parquet")
    monkeypatch.setattr(price_store, "VOLUME_FILE", tmp_path / "volume.parquet")
    days = pd.bdate_range("2024-01-01", periods=8)
    close = pd.DataFrame({"A": [100.0] * 8, "B": [np.nan] * 4 + [50.0] * 4}, index=days)
    volume = pd.DataFrame({"A": [1e5] * 4 + [3e5] * 4, "B": [np.nan] * 4 + [2e5] * 4}, index=days)
    close.to_parquet(tmp_path / "close.parquet")
    volume.to_parquet(tmp_path / "volume.parquet")
    return PriceStore(price_dir=tmp_path)


def test_adv_history_is_trailing_and_waits_for_min_periods(store):
    adv = store.adv_history(window=2, min_periods=2)
    # A: Rs 1 crore a day for four days, then Rs 3 crore; a two-day mean, in crore.
    assert adv["A"].tolist()[1:] == pytest.approx([1, 1, 1, 2, 3, 3, 3])
    assert np.isnan(adv["A"].iloc[0])
    # B lists on day 5: nothing until it has two sessions.
    assert adv["B"].isna().tolist() == [True] * 5 + [False] * 3
    assert adv["B"].iloc[-1] == pytest.approx(1.0)


def test_close_is_cleaned_by_default_and_raw_on_request(store):
    raw = store.close(clean=False)
    raw.loc[raw.index[5], "A"] = 1000.0   # a bad print, written to the panel
    raw.to_parquet(price_store.CLOSE_FILE)
    assert store.close(clean=False)["A"].max() == 1000.0
    assert store.close()["A"].max() == pytest.approx(100.0)
