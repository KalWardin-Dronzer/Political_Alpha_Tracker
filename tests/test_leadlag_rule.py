"""Tests for the cost charged by the lead-lag trading rule."""

import pandas as pd
import pytest

from src.research.factor_backtest import CostModel
from studies.leadlag_rule import trading_costs


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
