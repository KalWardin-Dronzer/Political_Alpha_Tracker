"""
Political Alpha Tracker — Universe Manager

Maintains a comprehensive database of all active listed companies.
Downloads the NSE equity list and maps symbols to BSE scrip codes
so that the daily pipeline can monitor the entire market for contract wins.
"""

import time
import logging
import requests
import pandas as pd
import io

from src.config import BSE_HEADERS
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)

NSE_EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

class UniverseManager:
    """Manages the full universe of monitorable stocks."""
    
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update(BSE_HEADERS)
    
    def get_full_universe_scrip_codes(self) -> list[str]:
        """
        Get all known BSE scrip codes from the database.
        Returns a list of scrip codes.
        """
        with self.cache._connect() as conn:
            rows = conn.execute("SELECT scrip_code FROM companies WHERE scrip_code IS NOT NULL").fetchall()
        return [row[0] for row in rows]
    
    def update_universe(self):
        """
        Downloads the latest NSE equity list and adds missing companies
        to our database by resolving their BSE scrip codes.
        Also backfills NSE symbols and sector data for existing companies.
        """
        logger.info("Updating stock universe...")
        
        # 1. Fetch NSE equity list
        try:
            nse_headers = {
                "User-Agent": BSE_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.nseindia.com/",
            }
            resp = requests.get(NSE_EQUITY_LIST_URL, headers=nse_headers, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip() for c in df.columns]
            
            # Keep only EQ series
            if "SERIES" in df.columns:
                df = df[df["SERIES"].str.strip() == "EQ"]
                
            logger.info(f"Fetched {len(df)} equity listings from NSE")
        except Exception as e:
            logger.error(f"Failed to fetch NSE equity listing: {e}")
            return
        
        # Build ISIN -> NSE data lookup for backfilling
        nse_lookup = {}
        for _, row in df.iterrows():
            isin = row.get("ISIN NUMBER", "")
            if isin:
                nse_lookup[isin] = {
                    "nse_symbol": row.get("SYMBOL", ""),
                    "sector": row.get("SECTOR", "") if "SECTOR" in df.columns else "",
                    "industry": row.get("INDUSTRY", "") if "INDUSTRY" in df.columns else "",
                }
        
        # 2. Backfill NSE symbols for existing companies that don't have one
        self._backfill_nse_symbols(nse_lookup)
            
        # 3. Get existing ISINs in DB
        with self.cache._connect() as conn:
            existing_isins = {r[0] for r in conn.execute("SELECT isin FROM companies WHERE isin IS NOT NULL").fetchall()}
            
        # 4. Find missing companies
        missing_df = df[~df["ISIN NUMBER"].isin(existing_isins)]
        logger.info(f"Found {len(missing_df)} new companies not in database. Resolving BSE scrips...")
        
        # 5. Resolve BSE scrip codes for missing companies
        MAX_RESOLVE_PER_RUN = 200
        resolved_count = 0
        
        for _, row in missing_df.head(MAX_RESOLVE_PER_RUN).iterrows():
            nse_symbol = row["SYMBOL"]
            name = row["NAME OF COMPANY"]
            isin = row["ISIN NUMBER"]
            face_value = row["FACE VALUE"]
            sector = row.get("SECTOR", "") if "SECTOR" in df.columns else ""
            industry = row.get("INDUSTRY", "") if "INDUSTRY" in df.columns else ""
            
            bse_scrip = self._resolve_bse_scrip(nse_symbol)
            if bse_scrip:
                self.cache.upsert_company(
                    scrip_code=bse_scrip,
                    name=name,
                    isin=isin,
                    cin="",
                    nse_symbol=nse_symbol,
                    sector=sector or "",
                    industry=industry or "",
                    micro_niche=industry or sector or "",
                    face_value=face_value,
                )
                with self.cache._connect() as conn:
                    conn.execute("UPDATE companies SET in_watchlist=0 WHERE scrip_code=?", (bse_scrip,))
                resolved_count += 1
            
            time.sleep(0.3)
            
        logger.info(f"Resolved and added {resolved_count} new companies to the universe.")
    
    def _backfill_nse_symbols(self, nse_lookup: dict):
        """Backfill NSE symbols and sector data for existing companies."""
        with self.cache._connect() as conn:
            rows = conn.execute(
                "SELECT scrip_code, isin FROM companies WHERE (nse_symbol IS NULL OR nse_symbol = '') AND isin IS NOT NULL"
            ).fetchall()
        
        if not rows:
            return
            
        backfilled = 0
        for row in rows:
            scrip_code = row[0]
            isin = row[1]
            nse_data = nse_lookup.get(isin)
            if nse_data and nse_data["nse_symbol"]:
                with self.cache._connect() as conn:
                    conn.execute(
                        "UPDATE companies SET nse_symbol=?, sector=COALESCE(NULLIF(sector,''), ?), "
                        "industry=COALESCE(NULLIF(industry,''), ?), "
                        "micro_niche=COALESCE(NULLIF(micro_niche,''), ?) "
                        "WHERE scrip_code=?",
                        (nse_data["nse_symbol"], 
                         nse_data.get("sector", ""), 
                         nse_data.get("industry", ""),
                         nse_data.get("industry") or nse_data.get("sector", ""),
                         scrip_code)
                    )
                backfilled += 1
        
        if backfilled:
            logger.info(f"Backfilled NSE symbols for {backfilled} existing companies.")
        
    def _resolve_bse_scrip(self, nse_symbol: str) -> str:
        """Search BSE for the NSE symbol and return the scrip code."""
        try:
            search_url = f"https://api.bseindia.com/Msource/1D/getQouteSearch.aspx?Type=EQ&text={nse_symbol}&flag=gq"
            resp = self.session.get(search_url, timeout=10)
            
            if resp.status_code == 200 and resp.text:
                import re
                match = re.search(r"href='[^']*?/(\d{6})/'", resp.text)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.debug(f"BSE scrip resolve failed for {nse_symbol}: {e}")
            
        return ""
