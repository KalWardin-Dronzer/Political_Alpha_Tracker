"""
Political Alpha Tracker — Cross-Sectional Factor Engine (Phase 1)

Ranks a liquidity-screened universe by expected return at a point in time.

WHY A FACTOR ENGINE
-------------------
The event-driven strategy this project began as produces ~1.17 tradeable
signals per year. Grinold's fundamental law puts information ratio at roughly
IC * sqrt(breadth), so at a breadth near one there is no achievable skill level
that yields a respectable risk-adjusted return. This module replaces a rare
high-conviction event with many small, simultaneous, independent bets.

THE THREE FACTORS
-----------------
1. Residual momentum (12 months, skipping the most recent month).
   Raw momentum in a small universe mostly measures sector drift — exactly the
   confound that made the project's own n=7 event study uninterpretable, where
   every "connected" name happened to be pharma. Regressing out the market
   before ranking leaves the idiosyncratic component. Skipping the most recent
   month keeps momentum from colliding with the reversal factor below.

2. Short-term reversal (1 week), negated.
   Documented as strongest in the least liquid names — the tier where retail
   can operate and size-constrained institutional capital cannot.

3. Low volatility, negated.
   Carried mainly as a risk modifier rather than a return driver.

Each is z-scored ACROSS the universe on each date (never through time), then
combined. Cross-sectional scoring is what makes these comparable: it asks
"which names look best today", not "is today a good day".

POINT-IN-TIME DISCIPLINE
------------------------
compute() uses only rows at or before `as_of`. The caller is still responsible
for the execution lag — see FactorEngine.LAG_DAYS. If a signal's performance
collapses when you add that lag, it was leaking, not working.

KNOWN LIMITATION
----------------
Residual momentum here regresses on the market only, not the full Fama-French
three-factor model. SMB and HML need historical book value and point-in-time
market cap, neither of which this project has yet (market cap is populated for
93 of 1,589 companies, and today's value applied to history would be
look-ahead). Market-residual is the honest version of what the data supports.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Factor parameters ────────────────────────────────────────────
MOMENTUM_LOOKBACK = 252      # ~12 months of sessions
MOMENTUM_SKIP = 21           # skip most recent month (momentum/reversal overlap)
REVERSAL_LOOKBACK = 5        # ~1 week
VOL_LOOKBACK = 63            # ~3 months

# Starting composite weights. NOT tuned — deliberately round numbers, because
# every weight combination tried is a trial that must be counted against the
# deflated Sharpe ratio in Phase 2. Tune these there, with the trial log, or
# not at all.
DEFAULT_WEIGHTS = {"residual_momentum": 0.45, "reversal": 0.35, "low_vol": 0.20}

MIN_ADV_CR = 1.0             # liquidity floor, Rs. crore of daily traded value
MIN_HISTORY_DAYS = 300       # need enough history for the momentum window
WINSOR_PCT = 0.02            # clip each tail before z-scoring
SCORE_CLIP = 3.0             # bound the final tilt so no name dominates


@dataclass
class FactorSnapshot:
    """Ranked universe at one point in time."""
    as_of: pd.Timestamp
    scores: pd.DataFrame                      # index=symbol, factor columns + composite
    universe_size: int
    screened_out: dict = field(default_factory=dict)

    def top(self, n: int = 20) -> pd.DataFrame:
        return self.scores.nlargest(n, "composite")

    def summary(self) -> str:
        return (
            f"{self.as_of.date()}: {self.universe_size} eligible "
            f"(screened out: {self.screened_out})"
        )


def _winsorize(s: pd.Series, pct: float = WINSOR_PCT) -> pd.Series:
    """Clip both tails. One bad print in an illiquid name can otherwise dominate a z-score."""
    if s.dropna().empty:
        return s
    lo, hi = s.quantile(pct), s.quantile(1 - pct)
    return s.clip(lo, hi)


def _zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score. Returns zeros (not NaN) if the cross-section is degenerate."""
    s = _winsorize(s)
    sd = s.std()
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / sd


class FactorEngine:
    """
        engine = FactorEngine(price_store)
        snap = engine.compute()          # as of the latest available session
        snap.top(20)
    """

    # Execution lag. Signals are computed from closes, so the earliest you could
    # act is the NEXT session's close — matching the backtester's T+1 execution.
    LAG_DAYS = 1

    def __init__(self, price_store, weights: dict = None,
                 min_adv_cr: float = MIN_ADV_CR, delisting_registry=None):
        self.store = price_store
        # Optional, but strongly recommended. Without it a panel that contains a
        # delisted symbol can be traded after its listing ended — look-ahead of
        # the worst kind, since the outcome is already known.
        self.registry = delisting_registry
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.min_adv_cr = min_adv_cr

        total = sum(self.weights.values())
        if not np.isclose(total, 1.0):
            logger.warning(f"Factor weights sum to {total:.3f}, normalising to 1.0")
            self.weights = {k: v / total for k, v in self.weights.items()}

    # ──────────────────────────────────────────
    # Factors
    # ──────────────────────────────────────────
    @staticmethod
    def residual_momentum(returns: pd.DataFrame,
                          market: pd.Series) -> pd.Series:
        """
        Cumulative market-residual return over [t-252, t-21].

        Beta is estimated on the SCORING WINDOW, not on the trailing 252
        sessions. That distinction is load-bearing: estimating it on a window
        that overlaps the skipped month lets a recent-month move change the
        beta, and therefore the residuals, and therefore the score — which
        silently defeats the skip whose whole job is to keep momentum from
        double-counting the reversal factor. A regression test covers this.

        beta comes from cov/var rather than a per-stock OLS loop: identical to
        the OLS slope for a single regressor, and it runs over the whole panel
        at once. No intercept is subtracted, so the summed residual is n * alpha
        — the idiosyncratic drift, which is exactly the quantity being ranked.
        """
        # Scoring window: MOMENTUM_LOOKBACK sessions, ending MOMENTUM_SKIP ago.
        scoring = returns.iloc[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP):-MOMENTUM_SKIP] \
            if MOMENTUM_SKIP > 0 else returns.tail(MOMENTUM_LOOKBACK)
        if scoring.empty:
            return pd.Series(dtype=float)

        mkt_s = market.reindex(scoring.index)
        mkt_var = mkt_s.var()
        if not np.isfinite(mkt_var) or mkt_var == 0:
            logger.warning("Market variance is zero — residual momentum unavailable")
            return pd.Series(dtype=float)

        betas = scoring.apply(lambda col: col.cov(mkt_s) / mkt_var)

        expected = pd.DataFrame(
            np.outer(mkt_s.values, betas.values),
            index=scoring.index, columns=scoring.columns,
        )
        residuals = scoring - expected
        return residuals.sum(axis=0, min_count=int(MOMENTUM_LOOKBACK * 0.6))

    @staticmethod
    def reversal(prices: pd.DataFrame) -> pd.Series:
        """Negated trailing 1-week return: recent losers score high."""
        if len(prices) < REVERSAL_LOOKBACK + 1:
            return pd.Series(dtype=float)
        window = prices.tail(REVERSAL_LOOKBACK + 1)
        return -(window.iloc[-1] / window.iloc[0] - 1.0)

    @staticmethod
    def low_vol(returns: pd.DataFrame) -> pd.Series:
        """Negated trailing realised volatility: calmer names score high."""
        if len(returns) < VOL_LOOKBACK:
            return pd.Series(dtype=float)
        return -returns.tail(VOL_LOOKBACK).std()

    # ──────────────────────────────────────────
    # Screening
    # ──────────────────────────────────────────
    def _eligible(self, prices: pd.DataFrame, as_of: pd.Timestamp) -> tuple[list, dict]:
        """Apply liquidity and history floors. Returns (symbols, rejection counts)."""
        rejected = {}

        history = prices.notna().sum()
        enough_history = history[history >= MIN_HISTORY_DAYS].index
        rejected["short_history"] = int((history < MIN_HISTORY_DAYS).sum())

        # Must have traded recently — a stale name is untradeable regardless of history.
        recent = prices.tail(5).notna().any()
        live = recent[recent].index
        rejected["stale"] = int((~recent).sum())

        eligible = enough_history.intersection(live)

        # Point-in-time delisting screen.
        if self.registry is not None:
            gone = self.registry.delisted_by(as_of)
            before = len(eligible)
            eligible = eligible.difference(gone)
            rejected["delisted"] = int(before - len(eligible))
        else:
            rejected["delisted"] = 0

        # as_of is required here — without it the screen uses future volume.
        adv = self.store.adv_cr(VOL_LOOKBACK, as_of=as_of)
        if not adv.empty:
            liquid = adv[adv >= self.min_adv_cr].index
            before = len(eligible)
            eligible = eligible.intersection(liquid)
            rejected["illiquid"] = int(before - len(eligible))
        else:
            logger.warning("No volume data — liquidity floor NOT applied")
            rejected["illiquid"] = 0

        return sorted(eligible), rejected

    # ──────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────
    def compute(self, as_of: Optional[str] = None) -> FactorSnapshot:
        """
        Rank the universe as of `as_of` (default: latest session in the panel).

        Only data at or before `as_of` is used.
        """
        prices = self.store.close()
        if prices.empty:
            raise ValueError("Price panel is empty — run PriceStore.update() first")

        prices.index = pd.to_datetime(prices.index)
        ts = pd.Timestamp(as_of) if as_of else prices.index.max()
        prices = prices.loc[prices.index <= ts]
        if prices.empty:
            raise ValueError(f"No price history at or before {ts.date()}")

        symbols, rejected = self._eligible(prices, ts)
        if not symbols:
            logger.error(f"No eligible symbols at {ts.date()} — screened out {rejected}")
            return FactorSnapshot(ts, pd.DataFrame(), 0, rejected)

        px = prices[symbols]
        rets = px.pct_change()

        # Equal-weighted universe return as the market proxy. Equal- rather than
        # cap-weighted: the strategy trades this universe, so this is the
        # relevant "market" to be neutral against, and it does not need the
        # point-in-time market caps the project lacks.
        market = rets.mean(axis=1)

        raw = pd.DataFrame({
            "residual_momentum": self.residual_momentum(rets, market),
            "reversal": self.reversal(px),
            "low_vol": self.low_vol(rets),
        })

        z = pd.DataFrame({c: _zscore(raw[c]) for c in raw.columns})

        composite = sum(z[c] * self.weights.get(c, 0.0) for c in z.columns)
        z["composite"] = composite.clip(-SCORE_CLIP, SCORE_CLIP)
        z["rank"] = z["composite"].rank(ascending=False, method="min").astype("Int64")

        for c in raw.columns:
            z[f"{c}_raw"] = raw[c]

        z = z.dropna(subset=["composite"]).sort_values("composite", ascending=False)

        logger.info(
            f"Factors @ {ts.date()}: {len(z)} ranked from {len(symbols)} eligible "
            f"(screened out: {rejected})"
        )
        return FactorSnapshot(ts, z, len(z), rejected)
