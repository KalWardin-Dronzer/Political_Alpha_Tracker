"""
Tests for the peer lead-lag test.

The critical property is group disjointness: if placebo leaders remained inside
the peer group, the regression would be predicting a basket partly from itself
and would manufacture a significant coefficient out of nothing. That is the one
bug here that would look like a discovery, so it is tested directly.
"""

import numpy as np
import pandas as pd
import pytest

from src.research.lead_lag import (
    LeadLagTest, SectorGroups, LeadLagResult,
    MIN_CONNECTED, MIN_PEERS,
)


class FakeStore:
    def __init__(self, close, adv=None):
        self._close = close
        self._adv = adv

    def close(self):
        return self._close.copy()

    def adv_cr(self, window=252, as_of=None):
        if self._adv is not None:
            return self._adv
        return pd.Series(10.0, index=self._close.columns)


def universe(rows):
    """A company table in the shape of data/companies.csv."""
    return pd.DataFrame([{"scrip_code": r["nse_symbol"], "isin": "", "industry": "", **r}
                         for r in rows])


def make_setup(n_days=900, seed=3):
    rng = np.random.default_rng(seed)
    syms = [f"C{i}" for i in range(4)] + [f"U{i}" for i in range(12)]
    idx = pd.bdate_range("2021-01-04", periods=n_days)
    px = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n_days))) for s in syms},
        index=idx,
    )
    rows = []
    for s in syms:
        connected = s.startswith("C")
        rows.append({"nse_symbol": s, "name": s, "sector": "TestSector",
                     "cin": f"CIN-{s}" if connected else ""})
    connected = {f"CIN-{s}" for s in syms if s.startswith("C")}
    return FakeStore(px), universe(rows), connected, syms


class TestGroupConstruction:
    def test_connected_and_peers_are_identified(self):
        store, companies, connected, _ = make_setup()
        groups = LeadLagTest(store, companies, connected).build_groups()
        assert len(groups) == 1
        g = groups[0]
        assert set(g.connected) == {"C0", "C1", "C2", "C3"}
        assert all(s.startswith("U") for s in g.peers)

    def test_placebo_is_disjoint_from_peers(self):
        """
        THE test. Overlap here would let the regression predict a basket from
        itself and fabricate significance.
        """
        store, companies, connected, _ = make_setup()
        g = LeadLagTest(store, companies, connected).build_groups()[0]
        assert set(g.placebo).isdisjoint(set(g.peers))

    def test_placebo_is_never_connected(self):
        """A placebo leader must be an UNCONNECTED stand-in, or it isn't a control."""
        store, companies, connected, _ = make_setup()
        g = LeadLagTest(store, companies, connected).build_groups()[0]
        assert set(g.placebo).isdisjoint(set(g.connected))

    def test_placebo_matches_connected_on_traded_value(self):
        """The control must resemble the treatment in size, or it controls for nothing."""
        rng = np.random.default_rng(1)
        idx = pd.bdate_range("2021-01-04", periods=900)
        syms = [f"C{i}" for i in range(2)] + [f"U{i}" for i in range(10)]
        px = pd.DataFrame(
            {s: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 900))) for s in syms},
            index=idx,
        )
        # Connected names trade ~50 Cr; give peers a wide spread around that.
        adv = pd.Series({**{f"C{i}": 50.0 for i in range(2)},
                         **{f"U{i}": float(v) for i, v in
                            enumerate([1, 2, 5, 48, 52, 100, 200, 300, 400, 500])}})
        rows = [{"nse_symbol": s, "name": s, "sector": "S",
                 "cin": f"CIN-{s}" if s.startswith("C") else ""} for s in syms]
        g = LeadLagTest(FakeStore(px, adv), universe(rows),
                        {f"CIN-C{i}" for i in range(2)}).build_groups()[0]
        # The closest ADV matches to 50 are U3 (48) and U4 (52).
        assert set(g.placebo) == {"U3", "U4"}

    def test_sector_with_too_few_connected_is_skipped(self):
        rng = np.random.default_rng(5)
        idx = pd.bdate_range("2021-01-04", periods=900)
        syms = ["C0"] + [f"U{i}" for i in range(10)]
        px = pd.DataFrame(
            {s: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 900))) for s in syms},
            index=idx,
        )
        rows = [{"nse_symbol": s, "name": s, "sector": "S",
                 "cin": "CIN-C0" if s == "C0" else ""} for s in syms]
        groups = LeadLagTest(FakeStore(px), universe(rows),
                             {"CIN-C0"}).build_groups()
        assert groups == []      # 1 connected < MIN_CONNECTED


class TestRegression:
    def test_runs_and_reports_both_arms(self):
        store, companies, connected, _ = make_setup()
        t = LeadLagTest(store, companies, connected)
        r = t.run_sector(t.build_groups()[0])
        assert r is not None
        assert r.n_obs > 30
        # Both arms must be populated — a missing placebo makes the result unreadable.
        assert r.treatment_beta is not None and r.placebo_beta is not None

    def test_random_data_yields_no_lead_lag(self):
        """On independent random walks the verdict must be the null."""
        store, companies, connected, _ = make_setup(seed=99)
        t = LeadLagTest(store, companies, connected)
        r = t.run_sector(t.build_groups()[0])
        assert r.verdict().startswith("NO EVIDENCE")


class TestVerdictLogic:
    def _mk(self, tb, tt, pb, pt):
        return LeadLagResult("x", 500, tb, tt, pb, pt, 0.01, 0.01)

    def test_insignificant_treatment_is_the_null(self):
        assert self._mk(0.3, 1.2, 0.0, 0.1).verdict().startswith("NO EVIDENCE")

    def test_a_significant_placebo_does_not_settle_the_question(self):
        """Both arms significant: the verdict must defer to the difference test."""
        assert "test the difference" in self._mk(0.20, 3.0, 0.18, 2.5).verdict()

    def test_connected_only_is_not_yet_political(self):
        assert "test the difference" in self._mk(0.40, 3.0, 0.05, 0.4).verdict()


class TestDifferenceTest:
    """The stacked regression behind studies/lead_lag.py."""

    @staticmethod
    def _pool(seed=0, extra=0.0, n_sectors=4, n_periods=400):
        rng = np.random.default_rng(seed)
        frames = []
        dates = pd.bdate_range("2020-01-03", periods=n_periods, freq="W-FRI")
        common = rng.normal(0, 0.02, n_periods)   # both leaders share this, as size does
        for s in range(n_sectors):
            conn = common + rng.normal(0, 0.02, n_periods)
            plac = common + rng.normal(0, 0.02, n_periods)
            peer = 0.3 * common + extra * conn + rng.normal(0, 0.02, n_periods)
            frames.append(pd.DataFrame({"peer": peer, "conn_lag": conn, "plac_lag": plac,
                                        "peer_lag": rng.normal(0, 0.02, n_periods),
                                        "mkt_lag": rng.normal(0, 0.02, n_periods), "date": dates}))
        return pd.concat(frames, ignore_index=True)

    def test_point_estimates_equal_the_separate_fits(self):
        import statsmodels.api as sm
        from studies.lead_lag import stacked_difference
        pool = self._pool()
        fit = stacked_difference(pool)
        sep = {col: sm.OLS(pool["peer"], sm.add_constant(pool[[col, "peer_lag", "mkt_lag"]])).fit().params[col]
               for col in ("conn_lag", "plac_lag")}
        assert fit.params["lead"] == pytest.approx(sep["plac_lag"])
        assert fit.params["lead_x_treat"] == pytest.approx(sep["conn_lag"] - sep["plac_lag"])

    def test_detects_a_real_difference_and_not_a_shared_one(self):
        from studies.lead_lag import stacked_difference
        shared = stacked_difference(self._pool(seed=1, extra=0.0))
        assert shared.pvalues["lead_x_treat"] > 0.05      # same leader effect in both arms
        extra = stacked_difference(self._pool(seed=1, extra=0.4))
        assert extra.params["lead_x_treat"] > 0 and extra.pvalues["lead_x_treat"] < 0.01
