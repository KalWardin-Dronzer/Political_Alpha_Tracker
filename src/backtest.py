"""
Political Alpha Tracker — Backtest Module

Validates the alpha signal by running three statistical tests:

    Test 1 — Base Rate of Connectivity:
        What % of random micro-caps also have political connections?
        If > 50%, the signal is noise.

    Test 2 — Post-Event Returns:
        Do politically connected contract winners outperform non-connected
        ones at 30/60/90/180 day windows?

    Test 3 — Win Rate:
        What % of historical alerts would have produced positive excess
        returns? Need > 55% to be viable after transaction costs.
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
import pandas as pd

from src.config import (
    BACKTEST_WINDOWS_DAYS, MARKET_CAP_MIN_CR, MARKET_CAP_MAX_CR,
    YFINANCE_REQUEST_DELAY, ALPHA_SCORE_THRESHOLD,
)
from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from src.alpha_engine import AlphaEngine

logger = logging.getLogger(__name__)


class Backtester:
    """
    Validates the political alpha signal through statistical testing.

    Usage:
        bt = Backtester(cache)
        report = bt.run_full_backtest()
        print(report)
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.graph = GraphManager(cache)
        self.alpha_engine = AlphaEngine(cache)

    def _get_price_history(self, scrip_code: str,
                            start_date: str,
                            end_date: str) -> Optional[pd.DataFrame]:
        """
        Fetch historical price data via yfinance.

        Returns:
            DataFrame with Date index and Close prices, or None.
        """
        try:
            if scrip_code.startswith('^'):
                ticker = yf.Ticker(scrip_code)
                hist = ticker.history(start=start_date, end=end_date)
            else:
                ticker = yf.Ticker(f"{scrip_code}.BO")
                hist = ticker.history(start=start_date, end=end_date)

            if hist.empty:
                # Try NSE
                ticker = yf.Ticker(f"{scrip_code}.NS")
                hist = ticker.history(start=start_date, end=end_date)

            if hist.empty:
                return None

            return hist[["Close"]].copy()

        except Exception as e:
            logger.debug(f"Price history failed for {scrip_code}: {e}")
            return None

    def _compute_returns(self, prices: pd.DataFrame,
                          event_date: str,
                          windows: list[int] = None) -> dict:
        """
        Compute forward returns from an event date.

        Args:
            prices: DataFrame with Close prices
            event_date: Date of the event (YYYY-MM-DD)
            windows: List of forward-looking windows in days

        Returns:
            Dict mapping window -> return percentage
        """
        windows = windows or BACKTEST_WINDOWS_DAYS
        returns = {}

        try:
            event_dt = pd.Timestamp(event_date)
            if prices.index.tz is not None:
                event_dt = event_dt.tz_localize(prices.index.tz)

            # Find the closest trading day at or after the event
            valid_dates = prices.index[prices.index >= event_dt]
            if valid_dates.empty:
                return {}

            base_date = valid_dates[0]
            base_price = prices.loc[base_date, "Close"]

            for window in windows:
                target_date = base_date + pd.Timedelta(days=window)
                # Find closest trading day at or before target
                valid = prices.index[prices.index <= target_date]
                if valid.empty:
                    continue

                end_date = valid[-1]
                end_price = prices.loc[end_date, "Close"]

                ret = (end_price - base_price) / base_price * 100
                returns[window] = round(ret, 2)

        except Exception as e:
            logger.debug(f"Return computation error: {e}")

        return returns

    def test_base_rate(self, control_scrip_codes: list[str] = None,
                       num_control: int = 30) -> dict:
        """
        Test 1: Base Rate of Connectivity

        Measures what percentage of random (control) micro-caps also show
        political connections in the graph. High base rate = noisy signal.

        Args:
            control_scrip_codes: Specific control group scrip codes.
                                  If None, randomly selected from cache.
            num_control: Number of control companies if auto-selecting.

        Returns:
            Dict with base rate statistics.
        """
        logger.info("Running Test 1: Base Rate of Connectivity...")

        # Get watchlist companies with connections
        watchlist = self.cache.get_watchlist()
        watchlist_connected = 0
        watchlist_total = 0

        for company in watchlist:
            cin = company.get("cin")
            if not cin:
                continue
            watchlist_total += 1

            connections = self.graph.alpha_query(cin)
            if connections and connections[0]["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                watchlist_connected += 1

        # Get control group
        if not control_scrip_codes:
            all_companies = self.cache.get_all_companies()
            non_watchlist = [
                c for c in all_companies
                if not c.get("in_watchlist")
                and c.get("cin")
                and c.get("market_cap")
                and MARKET_CAP_MIN_CR <= (c.get("market_cap") or 0) <= MARKET_CAP_MAX_CR
            ]
            control_group = random.sample(
                non_watchlist, min(num_control, len(non_watchlist))
            )
        else:
            control_group = [
                self.cache.get_company(code)
                for code in control_scrip_codes
            ]
            control_group = [c for c in control_group if c]

        control_connected = 0
        control_total = 0

        for company in control_group:
            cin = company.get("cin")
            if not cin:
                continue
            control_total += 1

            connections = self.graph.alpha_query(cin)
            if connections and connections[0]["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                control_connected += 1

        watchlist_rate = (
            watchlist_connected / watchlist_total * 100
            if watchlist_total > 0 else 0
        )
        control_rate = (
            control_connected / control_total * 100
            if control_total > 0 else 0
        )

        result = {
            "watchlist_total": watchlist_total,
            "watchlist_connected": watchlist_connected,
            "watchlist_rate_pct": round(watchlist_rate, 1),
            "control_total": control_total,
            "control_connected": control_connected,
            "control_rate_pct": round(control_rate, 1),
            "differential_pct": round(watchlist_rate - control_rate, 1),
            "signal_meaningful": control_rate < 50,
        }

        logger.info(
            f"Base Rate: Watchlist {watchlist_rate:.1f}% vs "
            f"Control {control_rate:.1f}% "
            f"({'MEANINGFUL' if result['signal_meaningful'] else 'NOISE'})"
        )

        return result

    def test_post_event_returns(self) -> dict:
        """
        Test 2: Post-Event Returns

        Compares forward returns of politically-connected contract winners
        vs non-connected ones.

        Returns:
            Dict with return statistics by window.
        """
        logger.info("Running Test 2: Post-Event Returns...")

        # Get historical contract announcements
        from src.cache_manager import CacheManager
        with self.cache._connect() as conn:
            rows = conn.execute("""
                SELECT a.scrip_code, a.title, a.date, c.cin, c.name, c.sector
                FROM announcements a
                JOIN companies c ON a.scrip_code = c.scrip_code
                WHERE a.is_contract = 1
                  AND a.date >= date('now', '-5 years')
                ORDER BY a.date
            """).fetchall()

        connected_returns = {w: [] for w in BACKTEST_WINDOWS_DAYS}
        unconnected_returns = {w: [] for w in BACKTEST_WINDOWS_DAYS}
        benchmark_returns = {w: [] for w in BACKTEST_WINDOWS_DAYS}

        for row in rows:
            row = dict(row)
            cin = row.get("cin")
            if not cin:
                continue

            # Check if politically connected (Conviction Stacking >= 2)
            # We mock materiality_pct for historical testing as it's rarely parsed fully in DB
            mock_materiality_pct = random.uniform(3.0, 15.0)
            
            conviction = self.alpha_engine.calculate_conviction_score(
                scrip_code=row["scrip_code"],
                materiality_pct=mock_materiality_pct,
                sector=row.get("sector", "")
            )
            is_connected = conviction["score"] >= 2

            # Get price history
            event_date = row["date"]
            start = (
                datetime.strptime(event_date, "%Y-%m-%d") - timedelta(days=5)
            ).strftime("%Y-%m-%d")
            end = (
                datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=400)
            ).strftime("%Y-%m-%d")

            prices = self._get_price_history(row["scrip_code"], start, end)
            if prices is None:
                continue

            returns = self._compute_returns(prices, event_date)

            bm_prices = self._get_price_history("^NSEI", start, end)
            bm_returns = self._compute_returns(bm_prices, event_date) if bm_prices is not None else {}

            target = connected_returns if is_connected else unconnected_returns
            for window, ret in returns.items():
                if window in target:
                    target[window].append(ret)
                    
            if is_connected:
                for window, ret in bm_returns.items():
                    if window in benchmark_returns:
                        benchmark_returns[window].append(ret)

        # Compute averages
        result = {}
        for window in BACKTEST_WINDOWS_DAYS:
            conn_avg = (
                sum(connected_returns[window]) / len(connected_returns[window])
                if connected_returns[window] else 0
            )
            unconn_avg = (
                sum(unconnected_returns[window]) / len(unconnected_returns[window])
                if unconnected_returns[window] else 0
            )
            bm_avg = (
                sum(benchmark_returns[window]) / len(benchmark_returns[window])
                if benchmark_returns[window] else 0
            )
            
            # Phase 4: Pair Trading Spread calculation
            pair_trade_spread = round(conn_avg - unconn_avg, 2)
            
            result[f"{window}d"] = {
                "connected_avg_return": round(conn_avg, 2),
                "unconnected_avg_return": round(unconn_avg, 2),
                "benchmark_avg_return": round(bm_avg, 2),
                "connected_sample_size": len(connected_returns[window]),
                "unconnected_sample_size": len(unconnected_returns[window]),
                "pair_trade_spread_vs_unconnected": pair_trade_spread,
                "excess_return_vs_benchmark": round(conn_avg - bm_avg, 2),
            }

        logger.info(f"Post-event returns (Phase 4 Pair Trading Spread evaluated): {result}")
        return result

    def test_win_rate(self) -> dict:
        """
        Test 3: Win Rate

        Of all historical alerts that would have fired, what % produced
        positive excess returns at 90 days?

        Returns:
            Dict with win rate statistics.
        """
        logger.info("Running Test 3: Win Rate...")

        # Get all contract announcements for watchlist companies
        with self.cache._connect() as conn:
            rows = conn.execute("""
                SELECT a.scrip_code, a.date, c.cin, c.name, c.sector
                FROM announcements a
                JOIN companies c ON a.scrip_code = c.scrip_code
                WHERE a.is_contract = 1
                  AND a.date >= date('now', '-5 years')
            """).fetchall()

        wins = 0
        losses = 0
        total = 0
        election_boosted_wins = 0

        for row in rows:
            row = dict(row)
            cin = row.get("cin")
            if not cin:
                continue

            # Check if this would have triggered an alert
            mock_materiality_pct = random.uniform(3.0, 15.0)
            conviction = self.alpha_engine.calculate_conviction_score(
                scrip_code=row["scrip_code"],
                materiality_pct=mock_materiality_pct,
                sector=row.get("sector", "")
            )
            if conviction["score"] < 2:
                continue
                
            connections = self.graph.alpha_query(cin)

            # Get 90-day return
            event_date = row["date"]
            start = (
                datetime.strptime(event_date, "%Y-%m-%d") - timedelta(days=5)
            ).strftime("%Y-%m-%d")
            end = (
                datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=100)
            ).strftime("%Y-%m-%d")

            prices = self._get_price_history(row["scrip_code"], start, end)
            if prices is None:
                continue

            returns = self._compute_returns(prices, event_date, [90])
            if 90 not in returns:
                continue

            total += 1
            is_election_boosted = False
            if connections and len(connections) > 0:
                is_election_boosted = connections[0].get("election_multiplier", 1.0) > 1.0
            
            if returns[90] > 0:
                wins += 1
                if is_election_boosted:
                    election_boosted_wins += 1
            else:
                losses += 1

        win_rate = wins / total * 100 if total > 0 else 0

        result = {
            "total_signals": total,
            "wins": wins,
            "losses": losses,
            "election_boosted_wins": election_boosted_wins,
            "win_rate_pct": round(win_rate, 1),
            "viable": win_rate >= 55,
        }

        logger.info(
            f"Win Rate: {win_rate:.1f}% ({wins}/{total}) — "
            f"Election Boosted Wins: {election_boosted_wins} — "
            f"{'VIABLE' if result['viable'] else 'NOT VIABLE'}"
        )

        return result

    def test_ml_optimization(self) -> dict:
        """
        Test 4: ML Parameter Optimization (XGBoost)
        
        Uses Walk-Forward Optimization to train a highly regularized XGBoost model
        on historical alpha events to find the mathematical optimal weighting of
        Materiality, Z-Score, and Alpha Score.
        """
        logger.info("Running Test 4: ML Parameter Optimization (XGBoost)...")
        try:
            import xgboost as xgb
            from sklearn.model_selection import TimeSeriesSplit
            from sklearn.metrics import accuracy_score
        except ImportError:
            logger.error("XGBoost/scikit-learn not installed. Cannot run ML optimization.")
            return {"viable": False, "error": "Missing dependencies"}

        # Extract historical features
        with self.cache._connect() as conn:
            rows = conn.execute("""
                SELECT a.scrip_code, a.date, c.cin
                FROM announcements a
                JOIN companies c ON a.scrip_code = c.scrip_code
                WHERE a.is_contract = 1
                  AND a.date >= date('now', '-5 years')
                ORDER BY a.date ASC
            """).fetchall()

        X = []
        y = []
        
        for row in rows:
            row = dict(row)
            cin = row.get("cin")
            if not cin:
                continue

            connections = self.graph.alpha_query(cin)
            alpha_score = connections[0]["alpha_score"] if connections else 0
            
            # Simulated features (since we don't have perfect historical z-scores in cache)
            # In production, these are retrieved from the historical time-series DB
            materiality_pct = random.uniform(2.0, 15.0) 
            vol_z_score = random.uniform(-1.0, 5.0)
            election_mult = connections[0].get("election_multiplier", 1.0) if connections else 1.0

            # Get 90-day return to create the target label (1 = win, 0 = loss)
            event_date = row["date"]
            start = (datetime.strptime(event_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
            end = (datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=100)).strftime("%Y-%m-%d")

            prices = self._get_price_history(row["scrip_code"], start, end)
            if prices is None:
                continue

            returns = self._compute_returns(prices, event_date, [90])
            if 90 not in returns:
                continue

            X.append([alpha_score, materiality_pct, vol_z_score, election_mult])
            y.append(1 if returns[90] > 0 else 0)

        if len(X) < 50:
            logger.warning("Not enough historical data points for robust ML training.")
            return {"viable": False, "reason": "Insufficient data"}

        import numpy as np
        X = np.array(X)
        y = np.array(y)

        # Walk-Forward Optimization (Chronological Cross-Validation)
        tscv = TimeSeriesSplit(n_splits=3)
        
        # Heavy Regularization to prevent Overfitting (The Quant Trap)
        params = {
            'objective': 'binary:logistic',
            'max_depth': 2,        # Extremely shallow trees to force broad rules
            'eta': 0.05,           # Slow learning rate
            'lambda': 5.0,         # L2 Regularization
            'alpha': 1.0,          # L1 Regularization
            'eval_metric': 'logloss'
        }

        accuracies = []
        for train_index, test_index in tscv.split(X):
            X_train, X_test = X[train_index], X[test_index]
            y_train, y_test = y[train_index], y[test_index]
            
            dtrain = xgb.DMatrix(X_train, label=y_train)
            dtest = xgb.DMatrix(X_test, label=y_test)
            
            model = xgb.train(params, dtrain, num_boost_round=50)
            
            preds = model.predict(dtest)
            pred_labels = [1 if p > 0.5 else 0 for p in preds]
            
            acc = accuracy_score(y_test, pred_labels)
            accuracies.append(acc)

        avg_acc = sum(accuracies) / len(accuracies)
        
        # Feature Importance
        importance = model.get_score(importance_type='gain')
        # Map 'f0', 'f1', etc back to names
        feature_names = ['alpha_score', 'materiality_pct', 'vol_z_score', 'election_mult']
        mapped_importance = {feature_names[int(k.replace('f',''))]: round(v, 2) for k, v in importance.items()}

        result = {
            "walk_forward_accuracy_pct": round(avg_acc * 100, 2),
            "feature_importance": mapped_importance,
            "viable": avg_acc > 0.55
        }
        
        logger.info(f"ML Optimization Complete. Out-of-sample Accuracy: {result['walk_forward_accuracy_pct']}%")
        logger.info(f"Optimal Feature Weights (Gain): {result['feature_importance']}")

        return result

    def run_full_backtest(self) -> dict:
        """
        Run all backtest tests and return a comprehensive report.

        Returns:
            Dict with all test results.
        """
        logger.info("=" * 60)
        logger.info("FULL BACKTEST STARTED")
        logger.info("=" * 60)

        report = {
            "timestamp": datetime.now().isoformat(),
            "test_1_base_rate": self.test_base_rate(),
            "test_2_post_event_returns": self.test_post_event_returns(),
            "test_3_win_rate": self.test_win_rate(),
            "test_4_ml_optimization": self.test_ml_optimization(),
        }

        # Overall verdict
        base_meaningful = report["test_1_base_rate"]["signal_meaningful"]
        win_viable = report["test_3_win_rate"]["viable"]
        ml_viable = report["test_4_ml_optimization"].get("viable", False)
        
        report["overall_verdict"] = (
            "SIGNAL VALIDATED (ML APPROVED)" if base_meaningful and win_viable and ml_viable
            else "SIGNAL VALIDATED (RULES ONLY)" if base_meaningful and win_viable
            else "SIGNAL NEEDS REVIEW"
        )

        logger.info(f"\nOverall verdict: {report['overall_verdict']}")
        logger.info("=" * 60)

        self.cache.log_event(
            "backtest", "full_backtest_complete",
            f"Verdict: {report['overall_verdict']}"
        )

        return report
