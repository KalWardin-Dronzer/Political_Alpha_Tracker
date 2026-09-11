"""
Tests for the cross-sectional factor engine.

These target the failure modes that would silently produce a plausible-looking
but wrong signal — look-ahead, sector confounding, degenerate cross-sections —
rather than just exercising the happy path. A factor engine that returns
numbers is easy; one that returns numbers for the right reasons is not.
"""

import numpy as np
import pandas as pd
import pytest

from src.signals.factor_engine import (
    FactorEngine, _zscore, _winsorize,
    MOMENTUM_LOOKBACK, MOMENTUM_SKIP,
)


class FakeStore:
    """Minimal PriceStore stand-in backed by in-memory frames."""

    def __init__(self, close: pd.DataFrame, volume: pd.DataFrame = None):
        self._close = close
        self._volume = volume if volume is not None else close * 0 + 1e6

    def close(self):
        return self._close.copy()

    def volume(self):
        return self._volume.copy()

    def adv_cr(self, window=63, as_of=None):
        # Mirrors the real PriceStore, INCLUDING honouring as_of. The earlier
        # version ignored as_of, which let a look-ahead bug in the liquidity
        # screen pass unit tests and only surface at the integration gate.
        px, vol = self._close, self._volume
        if as_of is not None:
            ts = pd.Timestamp(as_of)
            px = px.loc[px.index <= ts]
            vol = vol.loc[vol.index <= ts]
        common = px.columns.intersection(vol.columns)
        return ((px[common] * vol[common]).tail(window).mean() / 1e7).dropna()


def make_panel(n_days=600, symbols=("AAA", "BBB", "CCC", "DDD"), seed=7):
    """Random-walk price panel with enough history for every factor."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    data = {}
    for i, s in enumerate(symbols):
        steps = rng.normal(0.0004, 0.015, n_days)
        data[s] = 100 * np.exp(np.cumsum(steps))
    return pd.DataFrame(data, index=idx)


# ── helpers ──────────────────────────────────────────────────────

class TestScoring:
    def test_zscore_is_standardised(self):
        z = _zscore(pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
        assert abs(z.mean()) < 1e-9
        assert abs(z.std() - 1.0) < 0.35  # winsorising pulls the tails in slightly

    def test_zscore_of_constant_series_is_zero_not_nan(self):
        """A degenerate cross-section must not poison the composite with NaN."""
        z = _zscore(pd.Series([5.0] * 6))
        assert (z == 0).all()
        assert not z.isna().any()

    def test_winsorize_clips_an_outlier(self):
        s = pd.Series([1.0] * 50 + [1000.0])
        assert _winsorize(s).max() < 1000.0


# ── factors ──────────────────────────────────────────────────────

class TestFactors:
    def test_reversal_is_negated_recent_return(self):
        idx = pd.bdate_range("2024-01-01", periods=10)
        px = pd.DataFrame({
            "UP":   np.linspace(100, 120, 10),   # rose -> should score LOW
            "DOWN": np.linspace(120, 100, 10),   # fell -> should score HIGH
        }, index=idx)
        rev = FactorEngine.reversal(px)
        assert rev["DOWN"] > rev["UP"]
        assert rev["UP"] < 0

    def test_low_vol_prefers_the_calmer_name(self):
        rng = np.random.default_rng(3)
        idx = pd.bdate_range("2023-01-02", periods=100)
        rets = pd.DataFrame({
            "CALM":  rng.normal(0, 0.004, 100),
            "WILD":  rng.normal(0, 0.040, 100),
        }, index=idx)
        lv = FactorEngine.low_vol(rets)
        assert lv["CALM"] > lv["WILD"]

    def test_residual_momentum_strips_the_common_factor(self):
        """
        The whole point of residualising. Two names given an identical large
        market component plus different idiosyncratic drift must be ranked by
        the idiosyncratic part, not by the shared move.
        """
        n = MOMENTUM_LOOKBACK + MOMENTUM_SKIP + 60
        idx = pd.bdate_range("2021-01-04", periods=n)
        rng = np.random.default_rng(11)
        market = rng.normal(0.0006, 0.011, n)

        # Same beta-1 market exposure; WINNER has positive idiosyncratic drift.
        rets = pd.DataFrame({
            "WINNER": market + rng.normal(0.0010, 0.004, n),
            "LOSER":  market + rng.normal(-0.0010, 0.004, n),
        }, index=idx)
        mkt = pd.Series(market, index=idx)

        rm = FactorEngine.residual_momentum(rets, mkt)
        assert rm["WINNER"] > rm["LOSER"], "residual momentum failed to separate idiosyncratic drift"

    def test_residual_momentum_skips_the_recent_month(self):
        """
        A spike confined to the skip window must not move the score — that is
        what keeps momentum from double-counting the reversal factor.
        """
        n = MOMENTUM_LOOKBACK + MOMENTUM_SKIP + 40
        idx = pd.bdate_range("2021-01-04", periods=n)
        rng = np.random.default_rng(5)
        # A real market series: beta estimation needs non-zero variance, and a
        # flat market is not a case this factor is ever asked to handle.
        market = rng.normal(0.0005, 0.010, n)
        rets = pd.DataFrame({"AAA": market.copy(), "BBB": market.copy()}, index=idx)
        # Large move for BBB inside the skipped final month only.
        rets.iloc[-MOMENTUM_SKIP:, rets.columns.get_loc("BBB")] += 0.05
        mkt = pd.Series(market, index=idx)

        rm = FactorEngine.residual_momentum(rets, mkt)
        assert not rm.empty, "residual momentum returned nothing"
        assert abs(rm["AAA"] - rm["BBB"]) < 1e-6, "skip window leaked into momentum"


# ── engine ───────────────────────────────────────────────────────

class TestEngine:
    def test_compute_ranks_the_universe(self):
        store = FakeStore(make_panel())
        snap = FactorEngine(store).compute()
        assert snap.universe_size > 0
        assert "composite" in snap.scores.columns
        # Ranking is consistent with the composite it claims to rank by.
        ordered = snap.scores.sort_values("rank")["composite"]
        assert ordered.is_monotonic_decreasing

    def test_composite_is_bounded(self):
        store = FakeStore(make_panel())
        snap = FactorEngine(store).compute()
        assert snap.scores["composite"].abs().max() <= 3.0 + 1e-9

    def test_as_of_excludes_all_later_data(self):
        """Point-in-time discipline: the future must be invisible."""
        panel = make_panel()
        cutoff = panel.index[-40]

        full = FakeStore(panel)
        truncated = FakeStore(panel.loc[panel.index <= cutoff])

        a = FactorEngine(full).compute(as_of=str(cutoff.date()))
        b = FactorEngine(truncated).compute()

        common = a.scores.index.intersection(b.scores.index)
        assert len(common) > 0
        np.testing.assert_allclose(
            a.scores.loc[common, "composite"].values,
            b.scores.loc[common, "composite"].values,
            atol=1e-9,
            err_msg="compute(as_of=...) saw data after the cutoff",
        )

    def test_liquidity_floor_screens_thin_names(self):
        panel = make_panel(symbols=("LIQUID", "THIN"))
        vol = pd.DataFrame(
            {"LIQUID": 5e6, "THIN": 1.0},   # THIN trades ~nothing
            index=panel.index,
        )
        snap = FactorEngine(FakeStore(panel, vol), min_adv_cr=1.0).compute()
        assert "THIN" not in snap.scores.index
        assert snap.screened_out["illiquid"] >= 1

    def test_short_history_is_screened_out(self):
        panel = make_panel(n_days=600, symbols=("OLD", "NEW"))
        panel.loc[panel.index[:-50], "NEW"] = np.nan   # only 50 sessions of history
        snap = FactorEngine(FakeStore(panel)).compute()
        assert "NEW" not in snap.scores.index

    def test_empty_panel_raises_rather_than_returning_zeros(self):
        """
        An empty input must fail loudly. Returning an empty ranking would look
        like 'no opportunities today' — the same silent-null failure that hid
        the empty graph in the event pipeline.
        """
        with pytest.raises(ValueError):
            FactorEngine(FakeStore(pd.DataFrame())).compute()

    def test_weights_are_normalised(self):
        eng = FactorEngine(FakeStore(make_panel()),
                           weights={"residual_momentum": 2, "reversal": 1, "low_vol": 1})
        assert abs(sum(eng.weights.values()) - 1.0) < 1e-9
