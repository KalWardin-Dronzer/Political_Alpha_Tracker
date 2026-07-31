"""
Political Alpha Tracker — Volume Tracker (Phase 3)

Tracks daily volume spikes for highly connected watchlist companies.
Identifies "Smart Money Front-Running" by detecting > 3 standard deviation
spikes in 14-day average volume before a contract announcement.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

import yfinance as yf
import pandas as pd
import numpy as np

from src.config import YFINANCE_REQUEST_DELAY

logger = logging.getLogger(__name__)

@dataclass
class VolumeSpikeResult:
    scrip_code: str
    company_name: str
    is_spike: bool
    latest_volume: float
    mean_volume: float
    std_volume: float
    z_score: float
    reason: str = ""

class VolumeTracker:
    def __init__(self, cache):
        self.cache = cache
        
    def check_volume_spike(self, scrip_code: str, company_name: str, nse_symbol: str = None) -> VolumeSpikeResult:
        """
        Check if the latest daily volume is an anomaly (> 3 standard deviations).
        Uses a 14-day moving average.
        """
        ticker_symbol = f"{scrip_code}.BO"
        
        try:
            ticker = yf.Ticker(ticker_symbol)
            # Fetch 30 days to have enough data for a 14-day window + std deviation
            hist = ticker.history(period="1mo")
            
            if hist.empty and nse_symbol:
                ticker_symbol = f"{nse_symbol}.NS"
                ticker = yf.Ticker(ticker_symbol)
                hist = ticker.history(period="1mo")
                
            if hist.empty or len(hist) < 15:
                return VolumeSpikeResult(
                    scrip_code=scrip_code,
                    company_name=company_name,
                    is_spike=False,
                    latest_volume=0,
                    mean_volume=0,
                    std_volume=0,
                    z_score=0,
                    reason="Not enough volume data"
                )
                
            volumes = hist['Volume'].values
            
            # The latest day
            latest_volume = volumes[-1]
            
            # The previous 14 days (excluding today)
            prev_14_volumes = volumes[-15:-1]
            
            mean_vol = np.mean(prev_14_volumes)
            std_vol = np.std(prev_14_volumes)
            
            if std_vol == 0:
                z_score = 0
            else:
                z_score = (latest_volume - mean_vol) / std_vol
                
            is_spike = z_score > 3.0
            
            reason = f"Latest volume: {latest_volume:,.0f} | 14d Mean: {mean_vol:,.0f} | Z-Score: {z_score:.1f}"
            
            if is_spike:
                logger.warning(f"🚨 VOLUME SPIKE for {company_name}: {reason}")
            else:
                logger.info(f"  Volume normal for {company_name}: {reason}")
                
            return VolumeSpikeResult(
                scrip_code=scrip_code,
                company_name=company_name,
                is_spike=is_spike,
                latest_volume=latest_volume,
                mean_volume=mean_vol,
                std_volume=std_vol,
                z_score=z_score,
                reason=reason
            )
            
        except Exception as e:
            logger.error(f"Error checking volume for {scrip_code}: {e}")
            return VolumeSpikeResult(
                scrip_code=scrip_code,
                company_name=company_name,
                is_spike=False,
                latest_volume=0,
                mean_volume=0,
                std_volume=0,
                z_score=0,
                reason=f"Error: {e}"
            )
