"""
Political Alpha Tracker — Superstar Shareholding Tracker

Tracks the entry of known "superstar" investors (e.g., Ashish Kacholia, Vijay Kedia) 
into microcap/smallcap stocks.

Given the difficulty of scraping ASP.NET ViewState on BSE without a premium API, 
this module reads from the `superstar_holdings` SQLite table. 
Users can manually import quarterly CSVs into this table, or it can be populated 
by a future headless browser scraper.

In the meantime, real-time tracking is handled by `bulk_deal_monitor.py`.
"""

import logging
from typing import List, Dict

from src.cache_manager import CacheManager
from src.config import TRACKED_SUPERSTARS

logger = logging.getLogger(__name__)

class SuperstarTracker:
    def __init__(self, cache: CacheManager):
        self.cache = cache
        
    def check_superstar_entry(self, scrip_code: str) -> bool:
        """
        Checks if a tracked superstar has recently entered or increased 
        their stake in the given scrip code.
        """
        with self.cache._connect() as conn:
            cursor = conn.execute('''
                SELECT investor_name, holding_pct, is_new_entry 
                FROM superstar_holdings
                WHERE scrip_code = ?
                ORDER BY quarter_date DESC
                LIMIT 5
            ''', (scrip_code,))
            
            holdings = cursor.fetchall()
            
            for row in holdings:
                investor_name = row["investor_name"].upper()
                is_new = row["is_new_entry"]
                
                # Check if this investor is in our tracked list
                is_tracked = any(star in investor_name for star in TRACKED_SUPERSTARS)
                
                if is_tracked and is_new == 1:
                    logger.info(f"Superstar Entry Detected: {investor_name} in {scrip_code}")
                    return True
                    
        return False
        
    def get_tracked_holdings(self, scrip_code: str) -> List[Dict]:
        """Returns all tracked superstar holdings for a scrip."""
        with self.cache._connect() as conn:
            cursor = conn.execute('''
                SELECT investor_name, holding_pct, quarter_date
                FROM superstar_holdings
                WHERE scrip_code = ?
            ''', (scrip_code,))
            
            holdings = []
            for row in cursor.fetchall():
                investor_name = row["investor_name"].upper()
                if any(star in investor_name for star in TRACKED_SUPERSTARS):
                    holdings.append({
                        "investor_name": row["investor_name"],
                        "holding_pct": row["holding_pct"],
                        "quarter_date": row["quarter_date"]
                    })
                    
            return holdings
