"""Tests for the lead-lag trading rule: its costs and its point-in-time baskets."""

import numpy as np
import pandas as pd
import pytest

import studies.leadlag_rule as rule
from src.research.factor_backtest import CostModel
from studies.leadlag_rule import basket_groups, paired_bootstrap, trading_costs


def test_baskets_use_only_the_traded_value_known_at_the_time(monkeypatch):
    """Regression: leaders were once chosen by traded value at the END of the panel."""
    monkeypatch.setattr(rule, "N_LEADERS", 1)
    # Traded value known at the start of each period, Rs crore. C was tiny, then
    # became the most traded name; D was never liquid enough; E did not exist yet.
    known = pd.DataFrame({"A": [5.0, 5.0, 5.0], "B": [3.0, 3.0, 3.0], "C": [0.2, 4.0, 9.0],
                          "D": [0.5, 0.5, 0.5], "E": [np.nan, np.nan, 2.0]})
    leaders, peers = basket_groups(known)
    assert [leaders.loc[i][leaders.loc[i]].index.tolist() for i in range(3)] == [["A"], ["A"], ["C"]]
    assert [sorted(peers.loc[i][peers.loc[i]].index) for i in range(3)] == [["B"], ["B", "C"], ["A", "B", "E"]]


def test_a_round_trip_pays_buy_and_sell_once():
    """Regression: an earlier version charged a full round trip on entry AND on exit."""
    costs = CostModel()
    pos = pd.Series([0.0, 1.0, 1.0, 0.0])
    charged = trading_costs(pos, costs)
    assert list(charged) == pytest.approx([0.0, costs.buy_pct(), 0.0, costs.sell_pct()])
    assert charged.sum() == pytest.approx(costs.round_trip_pct())


def test_holding_from_the_first_period_pays_the_buy_side():
    costs = CostModel()
    charged = trading_costs(pd.Series([1.0, 1.0, 1.0]), costs)
    assert list(charged) == pytest.approx([costs.buy_pct(), 0.0, 0.0])


def test_the_paired_bootstrap_gives_the_same_interval_on_every_run():
    """Regression: the bootstrap was once unseeded, so its interval changed on every run."""
    rng = np.random.default_rng(1)
    bh = pd.Series(rng.normal(0.01, 0.05, 90))
    rule = bh * (rng.random(90) > 0.4)
    first, second = paired_bootstrap(rule, bh, n_boot=300), paired_bootstrap(rule, bh, n_boot=300)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, paired_bootstrap(rule, bh, n_boot=300, seed=7))
