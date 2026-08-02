"""
Political Alpha Tracker — Bulk & Block Deal Monitor

Monitors daily Bulk Deals and Block Deals on the NSE to detect large institutional 
money flows in real-time, matching against tracked superstars and political donors.
"""

import logging
import csv
import io
import time
from datetime import datetime
from typing import List, Dict, Set
import requests
from thefuzz import process, fuzz

from src.config import TRACKED_SUPERSTARS, DONOR_MATCH_SCORE
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)

class BulkDealMonitor:
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.session = requests.Session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
    def _get_cookies(self):
        """Fetch NSE home page to set required cookies."""
        try:
            self.session.get("https://www.nseindia.com", headers=self.headers, timeout=10)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Failed to fetch NSE cookies: {e}")

    def _fetch_csv(self, deal_type: str) -> List[Dict]:
        """Fetches bulk or block deal CSV from NSE."""
        url = f"https://nsearchives.nseindia.com/content/equities/{deal_type}.csv"
        try:
            resp = self.session.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                # Parse CSV
                content = resp.text
                if "NO RECORDS" in content:
                    return []
                
                reader = csv.DictReader(io.StringIO(content))
                deals = []
                for row in reader:
                    # Clean up keys which might have leading/trailing spaces
                    cleaned_row = {k.strip(): v.strip() for k, v in row.items() if k}
                    
                    if "Symbol" in cleaned_row and "Client Name" in cleaned_row:
                        deals.append(cleaned_row)
                return deals
            else:
                logger.warning(f"Failed to fetch {deal_type} deals: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Error fetching {deal_type} deals: {e}")
        return []

    def _get_known_donors(self) -> List[str]:
        """Fetch unique donor names from cache."""
        with self.cache._connect() as conn:
            cursor = conn.execute("SELECT DISTINCT donor_name FROM donors")
            return [row["donor_name"] for row in cursor.fetchall()]

    def _is_tracked_entity(self, client_name: str, donors: List[str]) -> bool:
        """Checks if the client name matches a tracked superstar or a donor."""
        client_upper = client_name.upper()
        
        # 1. Check Superstars
        for star in TRACKED_SUPERSTARS:
            if fuzz.token_set_ratio(star, client_upper) > 90:
                return True
                
        # 2. Check Donors (fuzzy match)
        if donors:
            match = process.extractOne(client_upper, donors, scorer=fuzz.token_set_ratio)
            if match and match[1] >= DONOR_MATCH_SCORE:
                return True
                
        # 3. Check major institutions (heuristics)
        # We could add a list of major DIIs/FIIs here if desired
        major_keywords = ["MUTUAL FUND", "CAPITAL", "SECURITIES", "HOLDINGS", "INVESTMENT", "ASSET MANAGEMENT", "FUND"]
        if any(keyword in client_upper for keyword in major_keywords):
            return True
            
        return False

    def scan_today_deals(self) -> List[Dict]:
        """Scans today's bulk and block deals for tracked entities buying."""
        self._get_cookies()
        
        all_deals = []
        all_deals.extend(self._fetch_csv("bulk"))
        all_deals.extend(self._fetch_csv("block"))
        
        donors = self._get_known_donors()
        tracked_buys = []
        
        with self.cache._connect() as conn:
            for deal in all_deals:
                scrip_code = deal.get("Symbol", "")
                client_name = deal.get("Client Name", "")
                buy_sell = deal.get("Buy/Sell", "").upper()
                quantity_str = deal.get("Quantity Traded", "0")
                if isinstance(quantity_str, str):
                    quantity = int(quantity_str.replace(",", "")) if quantity_str else 0
                else:
                    quantity = quantity_str
                    
                price_str = deal.get("Trade Price / Wght. Avg. Price", "0")
                if isinstance(price_str, str):
                    price = float(price_str.replace(",", "")) if price_str else 0.0
                else:
                    price = price_str
                    
                date_str = deal.get("Date", datetime.now().strftime("%d-%b-%Y"))
                
                # We only care about BUYs
                if buy_sell != "BUY":
                    continue
                    
                # Insert raw deal into DB
                conn.execute('''
                    INSERT INTO bulk_deals (scrip_code, deal_date, client_name, buy_sell, quantity, price)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (scrip_code, date_str, client_name, buy_sell, quantity, price))
                
                # Check if it's a tracked entity
                if self._is_tracked_entity(client_name, donors):
                    tracked_buys.append({
                        "scrip_code": scrip_code,
                        "client_name": client_name,
                        "quantity": quantity,
                        "price": price,
                        "date": date_str
                    })
                    
        return tracked_buys

    def has_recent_tracked_buy(self, scrip_code: str, days: int = 30) -> bool:
        """Checks if a scrip had a tracked bulk buy recently."""
        donors = self._get_known_donors()
        
        with self.cache._connect() as conn:
            cursor = conn.execute('''
                SELECT client_name FROM bulk_deals 
                WHERE scrip_code = ? AND buy_sell = 'BUY'
                ORDER BY id DESC LIMIT 50
            ''', (scrip_code,))
            
            for row in cursor.fetchall():
                if self._is_tracked_entity(row["client_name"], donors):
                    return True
                    
        return False
