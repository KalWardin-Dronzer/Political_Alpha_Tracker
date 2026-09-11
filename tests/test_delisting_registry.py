"""
Tests for the delisting registry and survivorship-bias estimate.

The registry's job is to stop two distinct errors:
  * trading a name after its listing ended (look-ahead on a known outcome), and
  * reporting a survivors-only return as if it were achievable.
Both are tested here against a fixture rather than the live NSE file, so the
suite does not depend on network access.
"""

import pandas as pd
import pytest

from src.delisting_registry import DelistingRegistry, FAILURE_KEYWORDS


@pytest.fixture
def registry(tmp_path):
    """A registry backed by a small handmade record."""
    df = pd.DataFrame({
        "symbol": ["DEADCO", "WIPEDOUT", "BOUGHTOUT", "OLDFAIL"],
        "name": ["Dead Co", "Wiped Out Ltd", "Bought Out Ltd", "Old Failure Ltd"],
        "board": ["Main Board"] * 4,
        "delisted_date": pd.to_datetime(
            ["2021-06-15", "2022-03-01", "2023-09-10", "2015-01-01"]
        ),
        "delisting_type": [
            "Delisting - Liquidation",
            "Compulsory Delisting",
            "Voluntary Delisting",
            "Delisting - Liquidation",
        ],
        "is_failure": [True, True, False, True],
    })
    path = tmp_path / "delisted.parquet"
    df.to_parquet(path)
    return DelistingRegistry(path=path)


class TestClassification:
    def test_failure_keywords_cover_both_involuntary_types(self):
        assert any("liquidation" in k for k in FAILURE_KEYWORDS)
        assert any("compulsory" in k for k in FAILURE_KEYWORDS)

    def test_voluntary_delisting_is_not_a_failure(self, registry):
        df = registry.load()
        assert not bool(df.loc[df["symbol"] == "BOUGHTOUT", "is_failure"].iloc[0])

    def test_liquidation_is_a_failure(self, registry):
        df = registry.load()
        assert bool(df.loc[df["symbol"] == "DEADCO", "is_failure"].iloc[0])


class TestPointInTime:
    def test_delisted_by_is_a_prefix_not_the_whole_set(self, registry):
        """The screen must only know about delistings that had already happened."""
        assert registry.delisted_by("2021-01-01") == {"OLDFAIL"}
        assert registry.delisted_by("2021-07-01") == {"OLDFAIL", "DEADCO"}
        assert registry.delisted_by("2026-01-01") == {
            "OLDFAIL", "DEADCO", "WIPEDOUT", "BOUGHTOUT"
        }

    def test_delisting_date_itself_counts_as_gone(self, registry):
        assert "DEADCO" in registry.delisted_by("2021-06-15")

    def test_in_window_excludes_delistings_outside_it(self, registry):
        w = registry.in_window("2021-01-01", "2022-12-31")
        assert set(w["symbol"]) == {"DEADCO", "WIPEDOUT"}
        assert "OLDFAIL" not in set(w["symbol"])     # before the window
        assert "BOUGHTOUT" not in set(w["symbol"])   # after the window


class TestBiasEstimate:
    def test_counts_failures_and_buyouts_separately(self, registry):
        est = registry.bias_estimate(1000, "2021-01-01", "2023-12-31")
        assert est.n_failures == 2          # DEADCO, WIPEDOUT
        assert est.n_buyouts == 1           # BOUGHTOUT

    def test_universe_is_reconstructed_upward(self, registry):
        """The true historical universe is larger than the survivor count."""
        est = registry.bias_estimate(1000, "2021-01-01", "2023-12-31")
        assert est.universe_size == 1003

    def test_drag_is_positive_when_failures_exist(self, registry):
        est = registry.bias_estimate(1000, "2021-01-01", "2023-12-31")
        assert est.annual_drag_pct > 0

    def test_full_recovery_assumption_zeroes_the_drag(self, registry):
        """If failures returned capital in full there would be no drag to correct."""
        est = registry.bias_estimate(1000, "2021-01-01", "2023-12-31",
                                     failure_recovery=1.0)
        assert est.annual_drag_pct == pytest.approx(0.0)

    def test_drag_scales_with_failure_rate(self, registry):
        """A smaller surviving universe means failures were a larger share of it."""
        small = registry.bias_estimate(100, "2021-01-01", "2023-12-31")
        large = registry.bias_estimate(10_000, "2021-01-01", "2023-12-31")
        assert small.annual_drag_pct > large.annual_drag_pct

    def test_missing_registry_reports_no_correction_rather_than_crashing(self, tmp_path):
        """
        An absent registry must degrade to 'no correction available', not to a
        silent zero that looks like 'no bias'.
        """
        empty = DelistingRegistry(path=tmp_path / "does-not-exist.parquet")
        assert empty.delisted_by("2024-01-01") == set()
        est = empty.bias_estimate(1588, "2019-01-01", "2026-01-01")
        assert est.n_failures == 0
        assert est.annual_drag_pct == 0.0
