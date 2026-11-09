"""
Tests for the event study.

The two ways it could mislead: a test that finds a reaction in noise (wrong
standard error, or an estimation window that includes the event), and controls
that are not comparable. Both are tested on synthetic prices with a known answer.
"""

import numpy as np
import pandas as pd
import pytest

from src.research.event_study import ESTIMATION, EVENTS, EventStudy


def panel(seed=0, jump=0.0, n_buyers=12, n_others=40):
    """Daily prices from 2023 to mid-2024: buyers B*, others U*, two sectors, a common market factor."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", "2024-06-28")
    market = rng.normal(0, 0.01, len(idx))
    syms = [f"B{i}" for i in range(n_buyers)] + [f"U{i}" for i in range(n_others)]
    rets = pd.DataFrame({s: market + rng.normal(0, 0.015, len(idx)) for s in syms}, index=idx)
    if jump:
        rets.loc[pd.Timestamp("2024-03-15"), [s for s in syms if s.startswith("B")]] += jump
    close = 100 * (1 + rets).cumprod()
    volume = pd.DataFrame({s: rng.uniform(1e5, 1e6) for s in syms}, index=idx)
    companies = pd.DataFrame([{"scrip_code": s, "nse_symbol": s, "name": s, "isin": "", "cin": "",
                               "sector": "A" if int(s[1:]) % 2 else "B", "industry": ""} for s in syms])
    connected = {s for s in syms if s.startswith("B")}
    return close, volume, companies, connected


def test_detects_a_known_reaction():
    study = EventStudy(*panel(jump=0.03))
    res = study.run()["results"].set_index(["event", "window"])
    car = res.loc[("names", "[0,+1]")]
    assert car["car"] == pytest.approx(0.03, abs=0.01)
    assert car["p"] < 0.01


def test_finds_nothing_in_noise():
    false_positives = 0
    for seed in range(20):
        res = EventStudy(*panel(seed=seed)).run()["results"].set_index(["event", "window"])
        false_positives += res.loc[("names", "[0,+1]"), "p"] < 0.05
    assert false_positives <= 3   # about 1 in 20 expected at the 5% level


def test_controls_come_from_the_same_sector_once_each():
    close, volume, companies, connected = panel()
    study = EventStudy(close, volume, companies, connected)
    pairs = study.match()
    sector = dict(zip(companies["nse_symbol"], companies["sector"]))
    assert len(pairs) == 12
    assert all(sector[b] == sector[c] for b, c in pairs)
    controls = [c for _, c in pairs]
    assert len(set(controls)) == len(controls) and not set(controls) & connected


def test_estimation_window_ends_before_the_first_event():
    study = EventStudy(*panel())
    first = study.pos[EVENTS[0].key]
    assert study.est.stop - 1 == first + ESTIMATION[1] < first


def test_a_stock_with_missing_prices_is_left_out():
    close, volume, companies, connected = panel()
    close.loc[pd.Timestamp("2024-03-15"), "B0"] = np.nan
    study = EventStudy(close, volume, companies, connected)
    assert "B0" not in study.eligible()
    assert "B0" not in [b for b, _ in study.match()]


def test_event_days_must_be_trading_days():
    close, volume, companies, connected = panel()
    with pytest.raises(ValueError):
        EventStudy(close.drop(pd.Timestamp("2024-03-15")), volume, companies, connected)
