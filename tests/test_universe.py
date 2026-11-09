"""Tests for the universe study's point-in-time screen and its index comparisons."""

import numpy as np
import pandas as pd
import pytest

import studies.universe as universe
from studies.universe import IndexDownloadError, index_returns, over_days, point_in_time_screen


def test_the_universe_on_a_day_uses_only_traded_value_from_before_it():
    """Regression: the screen once used traded value over the panel's LAST year."""
    days = pd.bdate_range("2024-01-01", periods=4)
    # Trailing traded value, Rs crore, as of each day's close. B becomes liquid
    # on day 2, so it can join the universe on day 3, not on day 2.
    adv = pd.DataFrame({"A": [5.0, 5.0, 5.0, 5.0], "B": [0.5, 0.5, 3.0, 3.0],
                        "C": [np.nan, 2.0, 2.0, 2.0]}, index=days)
    liquid, largest = point_in_time_screen(adv, days, ["A", "B", "C"], floor=1.0, top=1)
    assert liquid["B"].tolist() == [False, False, False, True]
    assert liquid["C"].tolist() == [False, False, True, True]
    assert liquid.iloc[0].tolist() == [False, False, False]   # nothing is known before the first day
    assert largest["A"].tolist() == [False, True, True, True]
    assert not largest[["B", "C"]].any().any()


def test_the_index_is_compared_over_the_portfolios_own_days():
    """Regression: criterion (c) once compared the index over 2019-2026 with a portfolio from 2020."""
    index = pd.Series(0.01, index=pd.bdate_range("2019-01-01", periods=10))
    portfolio_days = index.index[4:8]
    assert over_days(index, portfolio_days).index.equals(portfolio_days)


class _NoPrices:
    def __init__(self, ticker):
        self.ticker = ticker

    def history(self, start=None, end=None):
        return pd.DataFrame()


class _Unreachable:
    def __init__(self, ticker):
        raise ConnectionError("network unreachable")


@pytest.mark.parametrize("ticker_class", [_NoPrices, _Unreachable])
def test_a_failed_index_download_stops_the_study(monkeypatch, ticker_class):
    """Regression: an empty download once read as an index with a Sharpe ratio
    of zero, so every comparison against it, and the verdict, passed."""
    monkeypatch.setattr(universe.yf, "Ticker", ticker_class)
    with pytest.raises(IndexDownloadError):
        index_returns("^NSMIDCP", "2019-01-01", "2026-09-10")
