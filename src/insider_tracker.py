"""
Political Alpha Tracker — Insider Tracker (Phase 1 V2)

Monitors SEBI SAST and PIT disclosures from the Bombay Stock Exchange (BSE) 
to detect genuine "Smart Money" accumulation by promoters/directors.

Includes critical False-Signal Filters:
1. Transaction Type Filter: Only allows "Open Market Purchase".
2. Cluster Buy Heuristic: Requires multiple independent insiders buying, 
   or a massive individual capital deployment.
3. Net Accumulation Check: Nets out internal transfers.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import requests

from src.config import BSE_HEADERS, BSE_REQUEST_DELAY
from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from thefuzz import fuzz

logger = logging.getLogger(__name__)

# BSE SAST/PIT Endpoints (often protected, so we use robust error handling)
SAST_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/SastData/w"
PIT_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/InsiderTradingNew/w"

class InsiderTracker:
    def __init__(self, cache: CacheManager, graph: GraphManager = None):
        self.cache = cache
        self.graph = graph
        self.session = requests.Session()
        self.session.headers.update(BSE_HEADERS)
        
    def _fetch_disclosures(self, scrip_code: str, lookback_days: int = 30) -> List[Dict]:
        """
        Fetches SAST and PIT disclosures for a given scrip from BSE.
        """
        to_date = datetime.now().strftime("%Y%m%d")
        from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        
        params = {
            "pageno": "1",
            "strSearch": "P",
            "strPrevDate": from_date,
            "strToDate": to_date,
            "strScrip": scrip_code,
            "type": ""
        }
        
        disclosures = []
        
        # We try SAST first
        try:
            resp = self.session.get(SAST_API_URL, params=params, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and "Table" in data:
                        disclosures.extend(data["Table"])
                    elif isinstance(data, list):
                        disclosures.extend(data)
                except ValueError:
                    logger.debug(f"SAST API returned non-JSON for {scrip_code}")
        except Exception as e:
            logger.debug(f"Failed to fetch SAST for {scrip_code}: {e}")
            
        time.sleep(BSE_REQUEST_DELAY)
        
        # Then PIT
        try:
            resp = self.session.get(PIT_API_URL, params=params, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and "Table" in data:
                        disclosures.extend(data["Table"])
                    elif isinstance(data, list):
                        disclosures.extend(data)
                except ValueError:
                    logger.debug(f"PIT API returned non-JSON for {scrip_code}")
        except Exception as e:
            logger.debug(f"Failed to fetch PIT for {scrip_code}: {e}")
            
        return disclosures

    def detect_cluster_buy(self, scrip_code: str, lookback_days: int = 30) -> Optional[Dict]:
        """
        Applies False-Signal filters to Insider disclosures to find genuine 
        structural accumulation (Cluster Buys).
        
        Returns a dict with cluster details if a verified buy is detected, else None.
        """
        disclosures = self._fetch_disclosures(scrip_code, lookback_days)
        if not disclosures:
            return None
            
        # Filter 1: Open Market Only & Net Accumulation
        insider_flow = {}
        for d in disclosures:
            # Normalize fields across SAST and PIT
            acquirer = d.get("AcquirerName", d.get("PersonName", "Unknown")).upper()
            mode = d.get("ModeOfAcquisition", d.get("Mode", "")).upper()
            qty = float(d.get("NoOfShares", d.get("SecuritiesAcquired", 0)) or 0)
            buy_sell = d.get("BuySell", d.get("TransactionType", "")).upper()
            
            # STRICT FILTER: Ignore ESOP, Bonus, Off-Market, Scheme of Arrangement
            if "OPEN MARKET" not in mode and "MARKET PURCHASE" not in mode:
                continue
                
            if "S" in buy_sell or "DISPOSAL" in buy_sell:
                insider_flow[acquirer] = insider_flow.get(acquirer, 0) - qty
            elif "B" in buy_sell or "ACQUISITION" in buy_sell:
                insider_flow[acquirer] = insider_flow.get(acquirer, 0) + qty

        # Filter 2: The "Cluster Buy" Heuristic
        # We need at least 2 distinct insiders buying, OR one massive whale buying
        active_buyers = []
        total_shares_accumulated = 0
        
        for acquirer, net_shares in insider_flow.items():
            if net_shares > 0: # Only count net positive buyers
                active_buyers.append({
                    "name": acquirer,
                    "net_shares": net_shares
                })
                total_shares_accumulated += net_shares
                
        # Heuristic Thresholds
        is_cluster = len(active_buyers) >= 2
        is_whale = total_shares_accumulated >= 100_000 # Configurable threshold for "massive"
        
        is_political_insider_buy = False
        
        # New Filter: Political Alpha override
        if self.graph:
            company = self.cache.get_company(scrip_code)
            cin = company.get("cin") if company else None
            if cin:
                conns = self.graph.alpha_query(cin)
                if conns:
                    for buyer in active_buyers:
                        buyer_name = buyer["name"].upper()
                        for c in conns:
                            donor = (c.get("donor_company_name") or "").upper()
                            bureaucrat = (c.get("director_name") or "").upper()
                            
                            if donor and fuzz.token_set_ratio(donor, buyer_name) > 85:
                                is_political_insider_buy = True
                                logger.info(f"Political Insider Buy Detected! Donor {donor} matched {buyer_name}")
                                break
                            if bureaucrat and fuzz.token_set_ratio(bureaucrat, buyer_name) > 85:
                                is_political_insider_buy = True
                                logger.info(f"Political Insider Buy Detected! Bureaucrat {bureaucrat} matched {buyer_name}")
                                break
                        if is_political_insider_buy:
                            break

        if is_cluster or is_whale or is_political_insider_buy:
            return {
                "buyers_count": len(active_buyers),
                "total_shares": total_shares_accumulated,
                "top_buyers": active_buyers[:3],
                "is_cluster": is_cluster,
                "is_whale": is_whale,
                "is_political_insider_buy": is_political_insider_buy
            }
            
        return None

    def detect_sast_external_acquirer(self, scrip_code: str, lookback_days: int = 30) -> bool:
        """
        Detects if a non-promoter (external entity) has crossed the 5% threshold 
        (triggering a SAST filing) via Open Market purchases.
        """
        disclosures = self._fetch_disclosures(scrip_code, lookback_days)
        if not disclosures:
            return False
            
        for d in disclosures:
            mode = d.get("ModeOfAcquisition", d.get("Mode", "")).upper()
            buy_sell = d.get("BuySell", d.get("TransactionType", "")).upper()
            category = d.get("Category", d.get("PersonCategory", "")).upper()
            
            # Must be an acquisition via Open Market
            if "B" not in buy_sell and "ACQUISITION" not in buy_sell:
                continue
            if "OPEN MARKET" not in mode and "MARKET PURCHASE" not in mode:
                continue
                
            # Ignore Promoters
            if "PROMOTER" in category:
                continue
                
            # If it's SAST and they are not a promoter acquiring from open market,
            # they are an external acquirer (likely crossing 5%)
            # We can also check 'TotalHoldingAfter' if available, but the SAST 
            # filing itself is the trigger.
            if d.get("TotalHoldingAfter"):
                try:
                    pct = float(str(d.get("TotalHoldingAfter")).replace('%',''))
                    if pct >= 5.0:
                        return True
                except ValueError:
                    # If we can't parse it, still return True since they made a SAST filing
                    return True
            else:
                return True
                
        return False
