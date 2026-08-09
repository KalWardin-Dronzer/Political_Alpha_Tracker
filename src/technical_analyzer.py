"""
Political Alpha Tracker — Technical Analyzer (Entry Timing Engine)

Computes a suite of non-redundant technical indicators to determine
optimal entry timing for stocks flagged by the political alpha pipeline.

Indicators:
    1. RSI (14)           — Momentum (Overbought / Oversold)
    2. MACD (12,26,9)     — Short-term momentum crossover
    3. OBV               — Volume confirmation (smart money accumulation)
    4. SMA 50 / 200      — Macro trend (Golden Cross / Death Cross)
    5. ATR (14)           — Volatility (dynamic stop-loss calculation)
    6. VWAP              — Volume-weighted fair price

Produces a TechnicalScore (0-10) and Signal (STRONG_BUY / BUY / NEUTRAL / AVOID).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from src.config import YFINANCE_REQUEST_DELAY

logger = logging.getLogger(__name__)

# ── Configuration Constants ──────────────────────────────────────────
TA_RSI_PERIOD = 14
TA_MACD_FAST = 12
TA_MACD_SLOW = 26
TA_MACD_SIGNAL = 9
TA_SMA_SHORT = 50
TA_SMA_LONG = 200
TA_ATR_PERIOD = 14
TA_LOOKBACK_DAYS = 365  # Need 1 year for 200-day SMA

# Conviction integration weights
TA_CONVICTION_WEIGHT_STRONG_BUY = 2.5
TA_CONVICTION_WEIGHT_BUY = 1.0
TA_CONVICTION_PENALTY_AVOID = -1.5


@dataclass
class TechnicalResult:
    """Complete technical analysis result for a single stock."""
    scrip_code: str
    company_name: str
    signal: str  # STRONG_BUY, BUY, NEUTRAL, AVOID
    score: float  # 0-10
    conviction_adjustment: float  # Points to add/subtract from conviction

    # Individual indicators
    rsi: Optional[float] = None
    macd_value: Optional[float] = None
    macd_signal_line: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_bullish_crossover: bool = False
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    is_golden_cross: bool = False
    obv_trending_up: bool = False
    obv_latest: Optional[float] = None
    atr: Optional[float] = None
    atr_stop_loss: Optional[float] = None  # Suggested stop-loss price
    vwap: Optional[float] = None
    current_price: Optional[float] = None

    # Scoring breakdown
    breakdown: list = field(default_factory=list)

    # Raw data for charting
    price_data: Optional[pd.DataFrame] = None

    def summary(self) -> str:
        """Human-readable summary for Telegram alerts."""
        parts = [f"Signal: {self.signal} ({self.score}/10)"]
        if self.rsi is not None:
            parts.append(f"RSI: {self.rsi:.1f}")
        if self.macd_bullish_crossover:
            parts.append("MACD: Bullish ✅")
        else:
            parts.append("MACD: Bearish ❌")
        if self.is_golden_cross:
            parts.append("Trend: Golden Cross ✅")
        else:
            parts.append("Trend: Death Cross ❌")
        if self.obv_trending_up:
            parts.append("OBV: Accumulating ✅")
        else:
            parts.append("OBV: Distributing ❌")
        if self.atr_stop_loss is not None:
            parts.append(f"ATR Stop: ₹{self.atr_stop_loss:.2f}")
        return " | ".join(parts)


class TechnicalAnalyzer:
    """
    Computes technical indicators and produces a timing signal.

    Usage:
        ta = TechnicalAnalyzer(cache)
        result = ta.analyze("500325", "Reliance Industries")
        if result.signal == "STRONG_BUY":
            # Great entry timing!
    """

    def __init__(self, cache=None):
        self.cache = cache

    def _fetch_price_data(self, scrip_code: str, company_name: str,
                          nse_symbol: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """Fetch OHLCV price data from yfinance. If end_date is provided, fetches 1 year prior to that date."""
        # Auto-lookup NSE symbol
        if not nse_symbol and self.cache:
            company = self.cache.get_company(scrip_code)
            if company:
                nse_symbol = company.get("nse_symbol")

        hist = pd.DataFrame()
        
        start_date = None
        if end_date:
            try:
                from datetime import datetime, timedelta
                dt_end = datetime.strptime(end_date, "%Y-%m-%d")
                dt_start = dt_end - timedelta(days=365)
                start_date = dt_start.strftime("%Y-%m-%d")
            except Exception:
                pass

        # Try NSE first
        if nse_symbol:
            try:
                ticker = yf.Ticker(f"{nse_symbol}.NS")
                if start_date and end_date:
                    hist = ticker.history(start=start_date, end=end_date)
                else:
                    hist = ticker.history(period="1y")
            except Exception:
                pass

        # Fallback to BSE
        if hist.empty:
            try:
                ticker = yf.Ticker(f"{scrip_code}.BO")
                if start_date and end_date:
                    hist = ticker.history(start=start_date, end=end_date)
                else:
                    hist = ticker.history(period="1y")
            except Exception:
                pass

        if hist.empty or len(hist) < 50:
            logger.warning(
                f"Insufficient price data for {company_name} ({scrip_code}): "
                f"{len(hist)} bars"
            )
            return None

        time.sleep(YFINANCE_REQUEST_DELAY)
        return hist

    # ── Indicator Calculations ───────────────────────────────────────

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = TA_RSI_PERIOD) -> pd.Series:
        """Compute Relative Strength Index."""
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _compute_macd(close: pd.Series,
                      fast: int = TA_MACD_FAST,
                      slow: int = TA_MACD_SLOW,
                      signal: int = TA_MACD_SIGNAL) -> tuple:
        """Compute MACD, Signal Line, and Histogram."""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def _compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        """Compute On-Balance Volume."""
        direction = np.sign(close.diff())
        obv = (volume * direction).fillna(0).cumsum()
        return obv

    @staticmethod
    def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                     period: int = TA_ATR_PERIOD) -> pd.Series:
        """Compute Average True Range."""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(span=period, adjust=False).mean()
        return atr

    @staticmethod
    def _compute_vwap(high: pd.Series, low: pd.Series,
                      close: pd.Series, volume: pd.Series) -> pd.Series:
        """Compute Volume Weighted Average Price (rolling 20-day)."""
        typical_price = (high + low + close) / 3
        cumulative_tp_vol = (typical_price * volume).rolling(20).sum()
        cumulative_vol = volume.rolling(20).sum()
        vwap = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)
        return vwap

    # ── Main Analysis ────────────────────────────────────────────────

    def analyze(self, scrip_code: str, company_name: str = "",
                nse_symbol: str = None,
                price_data: pd.DataFrame = None,
                end_date: str = None) -> TechnicalResult:
        """
        Run full technical analysis on a stock.

        Args:
            scrip_code: BSE scrip code
            company_name: Company name (for logging)
            nse_symbol: Optional NSE symbol
            price_data: Optional pre-fetched OHLCV data
            end_date: Optional historical date (YYYY-MM-DD) for backtesting

        Returns:
            TechnicalResult with score, signal, indicators, and chart data.
        """
        logger.info(f"Running technical analysis for {company_name} ({scrip_code}){' up to ' + end_date if end_date else ''}")

        # Fetch data if not provided
        if price_data is None:
            price_data = self._fetch_price_data(scrip_code, company_name, nse_symbol, end_date)

        if price_data is None or price_data.empty:
            return TechnicalResult(
                scrip_code=scrip_code,
                company_name=company_name,
                signal="NEUTRAL",
                score=5.0,  # Default neutral when no data
                conviction_adjustment=0.0,
                breakdown=["No price data available — defaulting to NEUTRAL"]
            )

        close = price_data["Close"]
        high = price_data["High"]
        low = price_data["Low"]
        volume = price_data["Volume"]
        current_price = float(close.iloc[-1])

        # ── Compute all indicators ──
        rsi_series = self._compute_rsi(close)
        macd_line, signal_line, histogram = self._compute_macd(close)
        obv_series = self._compute_obv(close, volume)
        sma_50 = close.rolling(window=TA_SMA_SHORT).mean()
        sma_200 = close.rolling(window=TA_SMA_LONG).mean()
        atr_series = self._compute_atr(high, low, close)
        vwap_series = self._compute_vwap(high, low, close, volume)

        # ── Extract latest values ──
        rsi_val = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None
        macd_val = float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else None
        macd_sig = float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else None
        macd_hist = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else None
        sma_50_val = float(sma_50.iloc[-1]) if not pd.isna(sma_50.iloc[-1]) else None
        sma_200_val = float(sma_200.iloc[-1]) if not pd.isna(sma_200.iloc[-1]) else None
        atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None
        vwap_val = float(vwap_series.iloc[-1]) if not pd.isna(vwap_series.iloc[-1]) else None
        obv_latest = float(obv_series.iloc[-1]) if not pd.isna(obv_series.iloc[-1]) else None

        # ── Determine signals ──

        # MACD bullish crossover: MACD line crossed above signal line recently
        macd_bullish = False
        if len(histogram) >= 3:
            recent_hist = histogram.iloc[-3:]
            # Crossover = histogram went from negative to positive
            if recent_hist.iloc[-1] > 0 and recent_hist.iloc[0] <= 0:
                macd_bullish = True
            # Or histogram is positive and expanding
            elif recent_hist.iloc[-1] > 0 and recent_hist.iloc[-1] > recent_hist.iloc[-2]:
                macd_bullish = True

        # Golden cross
        golden_cross = False
        if sma_50_val is not None and sma_200_val is not None:
            golden_cross = sma_50_val > sma_200_val

        # OBV trending up (10-day slope)
        obv_up = False
        if len(obv_series) >= 10:
            obv_10d = obv_series.iloc[-10:]
            obv_slope = np.polyfit(range(10), obv_10d.values, 1)[0]
            obv_up = obv_slope > 0

        # Price above VWAP
        price_above_vwap = False
        if vwap_val is not None:
            price_above_vwap = current_price > vwap_val

        # ── SCORING (0-10) ──
        score = 0.0
        breakdown = []

        # 1. RSI (max +2)
        if rsi_val is not None:
            if rsi_val < 30:
                score += 2.0
                breakdown.append(f"+2.0 RSI Oversold ({rsi_val:.1f}) — Strong buy zone")
            elif rsi_val < 40:
                score += 1.5
                breakdown.append(f"+1.5 RSI Favorable ({rsi_val:.1f})")
            elif rsi_val < 55:
                score += 1.0
                breakdown.append(f"+1.0 RSI Neutral ({rsi_val:.1f})")
            elif rsi_val < 70:
                score += 0.5
                breakdown.append(f"+0.5 RSI Warm ({rsi_val:.1f})")
            else:
                score += 0.0
                breakdown.append(f"+0.0 RSI Overbought ({rsi_val:.1f}) — Caution!")

        # 2. MACD (max +2)
        if macd_bullish:
            score += 2.0
            breakdown.append("+2.0 MACD Bullish Crossover / Expansion")
        elif macd_hist is not None and macd_hist > 0:
            score += 1.0
            breakdown.append("+1.0 MACD Positive Histogram (Bullish)")
        else:
            breakdown.append("+0.0 MACD Bearish")

        # 3. SMA Trend (max +2)
        if golden_cross:
            # Also check if price is above both SMAs
            if current_price > sma_50_val:
                score += 2.0
                breakdown.append("+2.0 Golden Cross + Price above SMA50")
            else:
                score += 1.0
                breakdown.append("+1.0 Golden Cross (but price below SMA50)")
        elif sma_200_val is not None and current_price > sma_200_val:
            score += 0.5
            breakdown.append("+0.5 Price above SMA200 (weak uptrend)")
        else:
            breakdown.append("+0.0 Death Cross or Below SMA200")

        # 4. OBV (max +2)
        if obv_up:
            score += 2.0
            breakdown.append("+2.0 OBV Trending Up (Smart Money Accumulation)")
        else:
            breakdown.append("+0.0 OBV Trending Down (Distribution)")

        # 5. VWAP (max +2)
        if price_above_vwap:
            score += 2.0
            breakdown.append(f"+2.0 Price above VWAP (₹{vwap_val:.2f})")
        elif vwap_val is not None:
            score += 0.0
            breakdown.append(f"+0.0 Price below VWAP (₹{vwap_val:.2f})")

        # ── Determine signal ──
        if score >= 8:
            signal = "STRONG_BUY"
            conviction_adj = TA_CONVICTION_WEIGHT_STRONG_BUY
        elif score >= 6:
            signal = "BUY"
            conviction_adj = TA_CONVICTION_WEIGHT_BUY
        elif score >= 4:
            signal = "NEUTRAL"
            conviction_adj = 0.0
        else:
            signal = "AVOID"
            conviction_adj = TA_CONVICTION_PENALTY_AVOID

        breakdown.append(f"=> Technical Signal: {signal} (Score: {score}/10)")
        breakdown.append(f"=> Conviction Adjustment: {conviction_adj:+.1f}")

        # Calculate ATR-based stop loss
        atr_stop = None
        if atr_val is not None:
            atr_stop = current_price - (2.0 * atr_val)  # 2x ATR trailing stop

        # Enrich price_data with computed indicators for charting
        chart_data = price_data.copy()
        chart_data["RSI"] = rsi_series
        chart_data["MACD"] = macd_line
        chart_data["MACD_Signal"] = signal_line
        chart_data["MACD_Histogram"] = histogram
        chart_data["SMA_50"] = sma_50
        chart_data["SMA_200"] = sma_200
        chart_data["OBV"] = obv_series
        chart_data["ATR"] = atr_series
        chart_data["VWAP"] = vwap_series
        chart_data["ATR_Stop"] = close - (2.0 * atr_series)

        logger.info(f"  TA Result: {signal} ({score}/10) for {company_name}")
        for b in breakdown:
            logger.info(f"    {b}")

        return TechnicalResult(
            scrip_code=scrip_code,
            company_name=company_name,
            signal=signal,
            score=score,
            conviction_adjustment=conviction_adj,
            rsi=rsi_val,
            macd_value=macd_val,
            macd_signal_line=macd_sig,
            macd_histogram=macd_hist,
            macd_bullish_crossover=macd_bullish,
            sma_50=sma_50_val,
            sma_200=sma_200_val,
            is_golden_cross=golden_cross,
            obv_trending_up=obv_up,
            obv_latest=obv_latest,
            atr=atr_val,
            atr_stop_loss=atr_stop,
            vwap=vwap_val,
            current_price=current_price,
            breakdown=breakdown,
            price_data=chart_data,
        )

    def analyze_batch(self, companies: list[dict]) -> list[TechnicalResult]:
        """Run technical analysis on a batch of companies."""
        results = []
        for company in companies:
            result = self.analyze(
                scrip_code=company.get("scrip_code", ""),
                company_name=company.get("name", ""),
                nse_symbol=company.get("nse_symbol"),
            )
            results.append(result)
        return results
