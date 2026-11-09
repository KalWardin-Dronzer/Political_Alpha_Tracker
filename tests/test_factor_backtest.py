"""Tests for the backtest statistics: seeded intervals and the deflated Sharpe ratio."""

import numpy as np
import pandas as pd

from src.research.factor_backtest import bootstrap_sharpe_ci, deflated_sharpe_ratio


def _returns(seed=0, n=500, mean=0.0005):
    return pd.Series(np.random.default_rng(seed).normal(mean, 0.01, n))


def test_the_bootstrap_interval_is_the_same_on_every_run():
    """Regression: the intervals were once unseeded and changed on every run."""
    r = _returns()
    first, second = bootstrap_sharpe_ci(r), bootstrap_sharpe_ci(r)
    assert first == second
    assert first["ci_low"] < first["sharpe"] < first["ci_high"]


def test_more_trials_deflate_the_same_sharpe_ratio_further():
    r = _returns(mean=0.001)
    few, many = deflated_sharpe_ratio(r, n_trials=2), deflated_sharpe_ratio(r, n_trials=200)
    assert many["expected_max_noise_sharpe_annual"] > few["expected_max_noise_sharpe_annual"]
    assert many["dsr"] < few["dsr"]
