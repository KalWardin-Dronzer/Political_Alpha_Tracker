"""
Political Alpha Tracker — Factor Strategy Backtest & Validation (Phase 2)

Simulates the long-only cross-sectional factor strategy and then tries hard to
prove its result is luck.

WHY THIS IS SEPARATE FROM src/backtest.py
-----------------------------------------
That module event-studies discrete announcements. This one simulates a
continuously rebalanced portfolio, which needs turnover accounting, per-trade
costs and a daily return series. Different shape, different failure modes.

THE THREE THINGS THAT MAKE A BACKTEST HONEST
--------------------------------------------
1. COSTS SUBTRACTED PER TRADE, never as a haircut at the end. India's flat DP
   charge (Rs.15.93 per scrip per sell-day) is not proportional, so its drag
   depends on position size — a Rs.2,000 position pays ~1.0% in DP charges
   alone while a Rs.20,000 position pays ~0.10%. A percentage-only cost model
   silently flatters small accounts, which is exactly who this is for.

2. CONFIDENCE INTERVALS, not point estimates. A single Sharpe number from a
   single historical path carries no error bars. The stationary block bootstrap
   (Politis & Romano) resamples contiguous blocks, preserving the serial
   dependence an i.i.d. bootstrap would destroy. If the lower bound of that
   interval sits at or below zero, the point estimate means nothing.

3. A TRIAL COUNT. Every parameter combination tested is a chance to find noise
   that looks like signal. The deflated Sharpe ratio corrects for how many were
   tried — but only for the ones you actually logged. See TrialLog.

Purging and embargo are applied when splitting folds so that a training fold
cannot contain observations whose forward-return window overlaps the test fold.
"""

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

TRIAL_LOG_PATH = DATA_DIR / "backtest_trials.jsonl"
TRADING_DAYS = 252


# ──────────────────────────────────────────────────────────────
# Cost model
# ──────────────────────────────────────────────────────────────
@dataclass
class CostModel:
    """
    NSE equity delivery costs. Rates mirror src/portfolio_manager.py so the
    backtest and the paper trader cannot drift apart.
    """
    stt: float = 0.001            # 0.1% each side
    exchange_txn: float = 0.0000297
    sebi: float = 0.000001
    stamp_duty: float = 0.00015   # buy side only
    gst: float = 0.18             # on (brokerage + exchange + sebi)
    brokerage: float = 0.0        # zero-brokerage delivery
    dp_charge: float = 15.93      # FLAT, per scrip, per sell-day
    slippage: float = 0.0010      # 10 bps each side — small/mid-cap spread

    def buy_pct(self) -> float:
        variable = self.brokerage + self.exchange_txn + self.sebi
        return self.stt + variable + self.stamp_duty + variable * self.gst + self.slippage

    def sell_pct(self) -> float:
        variable = self.brokerage + self.exchange_txn + self.sebi
        return self.stt + variable + variable * self.gst + self.slippage

    def round_trip_pct(self) -> float:
        return self.buy_pct() + self.sell_pct()

    def dp_drag_pct(self, position_value: float) -> float:
        """The flat DP charge expressed as a fraction of one position's value."""
        if position_value <= 0:
            return 0.0
        return self.dp_charge / position_value


# ──────────────────────────────────────────────────────────────
# Results
# ──────────────────────────────────────────────────────────────
@dataclass
class BacktestResult:
    returns: pd.Series                       # daily NET strategy returns
    gross_returns: pd.Series
    benchmark: pd.Series
    turnover: pd.Series                      # fraction traded at each rebalance
    n_rebalances: int
    holdings_history: list = field(default_factory=list)
    params: dict = field(default_factory=dict)

    # ── metrics ──
    def sharpe(self, net: bool = True) -> float:
        r = self.returns if net else self.gross_returns
        if r.std() == 0 or r.empty:
            return 0.0
        return float(r.mean() / r.std() * math.sqrt(TRADING_DAYS))

    def annual_return(self, net: bool = True) -> float:
        r = self.returns if net else self.gross_returns
        if r.empty:
            return 0.0
        return float((1 + r).prod() ** (TRADING_DAYS / len(r)) - 1)

    def max_drawdown(self) -> float:
        if self.returns.empty:
            return 0.0
        curve = (1 + self.returns).cumprod()
        return float((curve / curve.cummax() - 1).min())

    def benchmark_sharpe(self) -> float:
        b = self.benchmark
        if b.empty or b.std() == 0:
            return 0.0
        return float(b.mean() / b.std() * math.sqrt(TRADING_DAYS))

    def annual_turnover(self) -> float:
        if self.turnover.empty or self.returns.empty:
            return 0.0
        years = len(self.returns) / TRADING_DAYS
        return float(self.turnover.sum() / years) if years else 0.0

    def cost_drag_annual(self) -> float:
        """Annualised gap between gross and net — what costs actually took."""
        return self.annual_return(net=False) - self.annual_return(net=True)

    def summary(self) -> dict:
        return {
            "sharpe_net": round(self.sharpe(), 3),
            "sharpe_gross": round(self.sharpe(net=False), 3),
            "annual_return_net_pct": round(self.annual_return() * 100, 2),
            "annual_return_gross_pct": round(self.annual_return(net=False) * 100, 2),
            "cost_drag_annual_pct": round(self.cost_drag_annual() * 100, 2),
            "max_drawdown_pct": round(self.max_drawdown() * 100, 2),
            "benchmark_sharpe": round(self.benchmark_sharpe(), 3),
            "annual_turnover_x": round(self.annual_turnover(), 2),
            "n_rebalances": self.n_rebalances,
            "n_days": len(self.returns),
        }


# ──────────────────────────────────────────────────────────────
# Trial log — the part that makes DSR meaningful
# ──────────────────────────────────────────────────────────────
class TrialLog:
    """
    Append-only record of every configuration backtested.

    The deflated Sharpe ratio only corrects for trials it knows about. Testing
    forty variants across three sessions and only remembering the promising
    ones makes DSR *more* misleading, not less — it certifies a number that was
    cherry-picked. So every run is logged automatically, including the failures.
    """

    def __init__(self, path: Path = TRIAL_LOG_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, params: dict, summary: dict):
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "params": params,
            "summary": summary,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    def all_sharpes(self) -> list[float]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(float(json.loads(line)["summary"]["sharpe_net"]))
                except Exception:
                    continue
        return out


# ──────────────────────────────────────────────────────────────
# Statistics
# ──────────────────────────────────────────────────────────────
def bootstrap_sharpe_ci(returns: pd.Series, n_boot: int = 1000,
                        block_size: int = 20, ci: float = 0.95) -> dict:
    """
    Stationary block bootstrap confidence interval for the annualised Sharpe.

    Blocks, not individual days: daily strategy returns are serially dependent,
    and an i.i.d. bootstrap would destroy that structure and produce an
    interval that is far too narrow.
    """
    r = returns.dropna()
    if len(r) < 60:
        return {"error": f"only {len(r)} observations — too few to bootstrap"}

    def _sharpe(x: np.ndarray) -> float:
        x = np.asarray(x).ravel()
        sd = x.std()
        return 0.0 if sd == 0 else x.mean() / sd * math.sqrt(TRADING_DAYS)

    try:
        from arch.bootstrap import StationaryBootstrap
        bs = StationaryBootstrap(block_size, r.values)
        lo, hi = bs.conf_int(_sharpe, n_boot, method="bca", size=ci).ravel()[:2]
        method = "bca"
    except Exception as e:
        # Manual stationary bootstrap: geometric block lengths, percentile CI.
        logger.warning(f"arch bootstrap unavailable ({e}); using percentile fallback")
        rng = np.random.default_rng(42)
        vals, n = [], len(r)
        for _ in range(n_boot):
            idx, p = [], 1.0 / block_size
            while len(idx) < n:
                start = rng.integers(0, n)
                while len(idx) < n:
                    idx.append(start % n)
                    start += 1
                    if rng.random() < p:
                        break
            vals.append(_sharpe(r.values[np.array(idx[:n])]))
        a = (1 - ci) / 2
        lo, hi = np.quantile(vals, [a, 1 - a])
        method = "percentile"

    point = _sharpe(r.values)
    return {
        "sharpe": round(point, 3),
        "ci_low": round(float(lo), 3),
        "ci_high": round(float(hi), 3),
        "method": method,
        "n_boot": n_boot,
        "block_size": block_size,
        "excludes_zero": bool(lo > 0),
    }


def deflated_sharpe_ratio(returns: pd.Series, n_trials: int,
                          benchmark_sr: float = 0.0) -> dict:
    """
    Bailey & Lopez de Prado's deflated Sharpe ratio.

    Answers: given that `n_trials` configurations were tested, what is the
    probability this Sharpe is genuinely above `benchmark_sr` rather than the
    best of many draws from noise?

    Computed on PER-PERIOD (daily) Sharpe — the variance correction assumes it.
    """
    r = returns.dropna()
    n = len(r)
    if n < 30:
        return {"error": f"only {n} observations"}

    sd = r.std()
    if sd == 0:
        return {"error": "zero variance"}

    sr = float(r.mean() / sd)                 # daily Sharpe
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))   # non-excess

    n_trials = max(int(n_trials), 1)

    # Expected maximum Sharpe under the null of no skill, across n_trials.
    euler = 0.5772156649
    if n_trials > 1:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        sr_var = 1.0 / math.sqrt(n)           # SD of Sharpe under the null
        sr0 = sr_var * ((1 - euler) * z1 + euler * z2)
    else:
        sr0 = 0.0
    sr0 = max(sr0, benchmark_sr / math.sqrt(TRADING_DAYS))

    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2
    if denom <= 0:
        return {"error": "non-normality correction degenerate"}

    dsr = float(stats.norm.cdf(((sr - sr0) * math.sqrt(n - 1)) / math.sqrt(denom)))

    return {
        "dsr": round(dsr, 4),
        "sharpe_annual": round(sr * math.sqrt(TRADING_DAYS), 3),
        "expected_max_noise_sharpe_annual": round(sr0 * math.sqrt(TRADING_DAYS), 3),
        "n_trials": n_trials,
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "n_obs": n,
        # 0.95 is the conventional bar: a <95% probability of genuine skill,
        # after accounting for search, is not a result worth trading.
        "passes": bool(dsr > 0.95),
    }


def purged_folds(dates: pd.DatetimeIndex, n_folds: int = 6,
                 purge_days: int = 21, embargo_days: int = 21) -> list[dict]:
    """
    Split a date index into folds, purging and embargoing around each test fold.

    Purge: drop training observations whose forward-return window overlaps the
    test fold. Embargo: additionally drop training observations immediately
    AFTER the test fold, since serial correlation leaks backwards too. Without
    both, a "walk-forward" test is quietly contaminated.
    """
    dates = pd.DatetimeIndex(dates).sort_values()
    n = len(dates)
    if n < n_folds * 2:
        return []

    bounds = np.linspace(0, n, n_folds + 1).astype(int)
    folds = []
    for i in range(n_folds):
        lo, hi = bounds[i], bounds[i + 1]
        test = dates[lo:hi]
        if len(test) == 0:
            continue
        purge_lo = test[0] - pd.Timedelta(days=purge_days)
        embargo_hi = test[-1] + pd.Timedelta(days=embargo_days)
        train = dates[(dates < purge_lo) | (dates > embargo_hi)]
        folds.append({
            "fold": i,
            "test_start": str(test[0].date()),
            "test_end": str(test[-1].date()),
            "n_train": len(train),
            "n_test": len(test),
            "train": train,
            "test": test,
        })
    return folds


# ──────────────────────────────────────────────────────────────
# The backtest
# ──────────────────────────────────────────────────────────────
class FactorBacktest:
    """
        bt = FactorBacktest(price_store)
        res = bt.run(top_n=20, rebalance_days=10)
        res.summary()
    """

    def __init__(self, price_store, cost_model: CostModel = None,
                 capital: float = 500_000.0):
        self.store = price_store
        self.costs = cost_model or CostModel()
        self.capital = capital

    def run(self, start: str = None, end: str = None, top_n: int = 20,
            rebalance_days: int = 10, weights: dict = None,
            min_adv_cr: float = 1.0, log_trial: bool = True,
            selection: str = "factor", seed: int = 42) -> BacktestResult:
        """
        Simulate the strategy.

        Signals are computed from the close of the rebalance date and executed
        at the NEXT session's close (T+1), matching src/backtest.py and removing
        any possibility of trading on information not yet available.

        `selection` controls how names are picked from the eligible universe:

          "factor"    — top_n by composite factor score (the strategy)
          "liquidity" — top_n by trailing traded value, ignoring every factor
          "random"    — top_n drawn at random from the eligible universe

        The last two are controls, not strategies. If "random" earns a Sharpe
        close to "factor", then the result is the universe's own return — a
        size and liquidity exposure — and the factor model is decoration. That
        comparison is the only thing that separates skill from beta here, and
        it is cheap enough that there is no excuse for skipping it.
        """
        rng = np.random.default_rng(seed)
        from src.factor_engine import FactorEngine

        prices = self.store.close()
        if prices.empty:
            raise ValueError("Price panel empty — run build_price_panel.py first")
        prices.index = pd.to_datetime(prices.index)

        if start:
            prices = prices.loc[prices.index >= pd.Timestamp(start)]
        if end:
            prices = prices.loc[prices.index <= pd.Timestamp(end)]

        all_dates = prices.index
        # Leave room for the momentum window before the first rebalance.
        first = 320
        if len(all_dates) <= first + rebalance_days:
            raise ValueError("Not enough history to backtest")

        rebal_idx = list(range(first, len(all_dates) - 1, rebalance_days))
        engine = FactorEngine(self.store, weights=weights, min_adv_cr=min_adv_cr)

        daily_rets = pd.Series(0.0, index=all_dates, dtype=float)
        gross_rets = pd.Series(0.0, index=all_dates, dtype=float)
        turnovers, holdings_hist = [], []
        held: set = set()

        for k, ri in enumerate(rebal_idx):
            signal_date = all_dates[ri]
            entry_i = ri + 1                      # T+1 execution
            exit_i = rebal_idx[k + 1] + 1 if k + 1 < len(rebal_idx) else len(all_dates) - 1
            if entry_i >= exit_i:
                continue

            try:
                snap = engine.compute(as_of=str(signal_date.date()))
            except Exception as e:
                logger.debug(f"factor compute failed at {signal_date.date()}: {e}")
                continue
            if snap.scores.empty:
                continue

            # All three selections draw from the SAME eligible universe, so the
            # only thing that differs is how names are chosen from it. That is
            # what makes the comparison a controlled one.
            eligible = list(snap.scores.index)
            if selection == "factor":
                picks = list(snap.top(top_n).index)
            elif selection == "liquidity":
                adv = self.store.adv_cr(63, as_of=str(signal_date.date()))
                ranked = adv.reindex(eligible).dropna().sort_values(ascending=False)
                picks = list(ranked.head(top_n).index)
            elif selection == "random":
                k = min(top_n, len(eligible))
                picks = list(rng.choice(eligible, size=k, replace=False))
            else:
                raise ValueError(f"unknown selection mode: {selection!r}")

            if not picks:
                continue

            # Turnover: fraction of the book replaced this rebalance.
            new = set(picks)
            turnover = 1.0 if not held else len(new - held) / max(len(new), 1)
            turnovers.append(turnover)

            # Costs charged once, at the rebalance, against the traded fraction.
            traded_names = len(new - held) if held else len(new)
            pct_cost = turnover * (self.costs.buy_pct() + self.costs.sell_pct())
            dp_cost = (traded_names * self.costs.dp_charge) / self.capital
            rebalance_cost = pct_cost + dp_cost

            window = prices.iloc[entry_i:exit_i + 1][picks]
            seg = window.pct_change().iloc[1:]
            if seg.empty:
                continue
            port = seg.mean(axis=1)               # equal weight

            gross_rets.loc[port.index] = port.values
            net = port.copy()
            net.iloc[0] = net.iloc[0] - rebalance_cost
            daily_rets.loc[net.index] = net.values

            held = new
            holdings_hist.append({
                "date": str(signal_date.date()),
                "n": len(picks),
                "turnover": round(turnover, 3),
                "cost_pct": round(rebalance_cost * 100, 4),
                "picks": picks[:10],
            })

        traded = daily_rets[daily_rets != 0].index
        if len(traded) == 0:
            raise ValueError("No trades simulated")
        span = slice(traded.min(), traded.max())

        bench = prices.loc[span].pct_change().mean(axis=1).fillna(0.0)

        params = {
            "selection": selection,
            "seed": seed if selection == "random" else None,
            "top_n": top_n,
            "rebalance_days": rebalance_days,
            "min_adv_cr": min_adv_cr,
            "weights": weights or "default",
            "capital": self.capital,
            "slippage_bps": self.costs.slippage * 1e4,
            "start": str(traded.min().date()),
            "end": str(traded.max().date()),
        }

        result = BacktestResult(
            returns=daily_rets.loc[span],
            gross_returns=gross_rets.loc[span],
            benchmark=bench,
            turnover=pd.Series(turnovers),
            n_rebalances=len(turnovers),
            holdings_history=holdings_hist,
            params=params,
        )

        if log_trial:
            TrialLog().record(params, result.summary())

        return result
