"""
Historical Ingestion Module for Backtesting (ED 500)

Scrapes 5 years of historical announcements from BSE for all watchlist companies.
This will take several hours to run due to rate limits.
"""

import os
import sys
# Add project root to PYTHONPATH so we can run this file directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.bse_monitor import BSEMonitor
from src.cache_manager import CacheManager
from src.config import BSE_REQUEST_DELAY

logger = logging.getLogger(__name__)

class HistoricalIngester:
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.monitor = BSEMonitor(cache)
        
    def fetch_historical_announcements(self, years: int = 5):
        """
        Fetch historical announcements for the last N years for all watchlist companies.
        """
        watchlist = self.cache.get_watchlist()
        total = len(watchlist)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * years)
        
        end_str = end_date.strftime("%Y%m%d")
        start_str = start_date.strftime("%Y%m%d")
        
        logger.info(f"Fetching historical announcements from {start_str} to {end_str}")
        
        for i, company in enumerate(watchlist, 1):
            scrip_code = company["scrip_code"]
            logger.info(f"[{i}/{total}] Fetching history for {company['name']} ({scrip_code})...")
            
            page = 1
            total_fetched = 0
            
            while True:
                logger.debug(f"  Page {page}...")
                raw_events = self.monitor._fetch_announcements(
                    scrip_code, start_str, end_str, page=page
                )
                
                if not raw_events:
                    break
                    
                total_fetched += len(raw_events)
                
                # Parse and save
                valid_events = []
                for item in raw_events:
                    title = item.get("HEADLINE", "")
                    dt_str = item.get("DT_TM", "")
                    if not title or not dt_str:
                        continue
                        
                    event_type = self.monitor._classify_announcement(title)
                    if event_type:
                        try:
                            # BSE format: 2024-07-25T14:30:00
                            dt_obj = datetime.fromisoformat(dt_str)
                            date_only = dt_obj.strftime("%Y-%m-%d")
                            
                            valid_events.append({
                                "scrip_code": scrip_code,
                                "title": title,
                                "date": date_only,
                                "category": item.get("CATEGORYNAME", ""),
                                "is_contract": 1 if event_type == "contract" else 0,
                                "is_board_change": 1 if event_type == "board_change" else 0,
                                "processed": 1, # Already processed for history
                            })
                        except ValueError:
                            pass
                            
                if valid_events:
                    with self.cache._connect() as conn:
                        for e in valid_events:
                            conn.execute("""
                                INSERT INTO announcements 
                                (scrip_code, title, date, category, is_contract, is_board_change, processed, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                e["scrip_code"], e["title"], e["date"], e["category"],
                                e["is_contract"], e["is_board_change"], e["processed"],
                                datetime.now().isoformat()
                            ))
                            
                page += 1
                time.sleep(BSE_REQUEST_DELAY)
                
            logger.info(f"  Saved {total_fetched} historical events for {scrip_code}")
            time.sleep(BSE_REQUEST_DELAY * 2) # Extra delay between companies

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cache = CacheManager(Path("data/cache.sqlite"))
    ingester = HistoricalIngester(cache)
    ingester.fetch_historical_announcements(years=5)
