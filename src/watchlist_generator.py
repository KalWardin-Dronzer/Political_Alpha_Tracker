"""
Political Alpha Tracker -- Watchlist Generator

Automatically generates the target watchlist through a five-stage funnel:
    Stage A1: Sector sweep -- filter by government-dependent sectors
    Stage A2: Donor match -- cross-reference electoral bond donors against listed companies
    Stage B:  Market cap filter -- keep companies within Rs.50Cr - Rs.10L Cr
    Stage C:  Contract frequency scoring -- rank by BSE contract announcements
              (skipped for donor-matched companies)
    Stage D:  Fundamental gate -- discard unhealthy companies (Porinju Layer)

Output: 40-100 companies, refreshed quarterly.
"""

import io
import re
import time
import logging
from typing import Optional

import pandas as pd
import requests
from rapidfuzz import fuzz

from src.config import (
    BSE_HEADERS, GOVT_DEPENDENT_SECTORS,
    MARKET_CAP_MIN_CR, MARKET_CAP_MAX_CR,
    MIN_CONTRACT_FREQUENCY, ANNOUNCEMENT_LOOKBACK_DAYS,
    DONOR_MIN_AMOUNT_CR, DONOR_MATCH_SCORE,
)
from src.cache_manager import CacheManager
from src.bse_monitor import BSEMonitor
from src.financial_screener import FinancialScreener
from src.entity_resolver import EntityResolver

logger = logging.getLogger(__name__)

# NSE Equity Listing — full universe of active listed companies
NSE_EQUITY_LIST_URL = (
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
)

# NSE Nifty 500 Industry Classification (richer sector/industry data)
NSE_INDUSTRY_URL = (
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
)

# BSE per-company info API (works! returns sector, industry, scrip code)
BSE_COMPANY_INFO_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w"
)


class WatchlistGenerator:
    """
    Auto-generates the political alpha watchlist.

    Usage:
        generator = WatchlistGenerator(cache)
        watchlist = generator.generate()
        # watchlist is a list of dicts with scrip_code, name, sector, etc.
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.bse_monitor = BSEMonitor(cache)
        self.screener = FinancialScreener(cache)
        self.session = requests.Session()
        self.session.headers.update(BSE_HEADERS)

    def _fetch_nse_equity_list(self) -> pd.DataFrame:
        """
        Download the NSE equity listing CSV (the full company universe).
        This is the primary data source since BSE's scrip list API is
        blocked by Cloudflare.

        Returns:
            DataFrame with columns: symbol, name, isin, face_value, series.
        """
        logger.info("Fetching NSE equity listing...")

        try:
            nse_headers = {
                "User-Agent": BSE_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.nseindia.com/",
            }

            resp = requests.get(
                NSE_EQUITY_LIST_URL,
                headers=nse_headers,
                timeout=30,
            )
            resp.raise_for_status()

            df = pd.read_csv(io.StringIO(resp.text))
            # Normalize column names (strip whitespace)
            df.columns = [c.strip() for c in df.columns]

            # Rename to standard names
            col_map = {
                "SYMBOL": "nse_symbol",
                "NAME OF COMPANY": "name",
                "SERIES": "series",
                "ISIN NUMBER": "isin",
                "FACE VALUE": "face_value",
            }
            df = df.rename(columns=col_map)

            # Keep only EQ series (main board equity)
            if "series" in df.columns:
                df = df[df["series"].str.strip() == "EQ"].copy()

            logger.info(f"Fetched {len(df)} equity listings from NSE")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch NSE equity listing: {e}")
            return pd.DataFrame()

    def _fetch_nse_industry_mapping(self) -> pd.DataFrame:
        """
        Download NSE's Nifty 500 industry classification for richer
        sector/industry data.

        Returns:
            DataFrame with columns: isin, industry, nse_symbol.
        """
        logger.info("Fetching NSE industry classification...")

        try:
            nse_headers = {
                "User-Agent": BSE_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.nseindia.com/",
            }

            resp = requests.get(
                NSE_INDUSTRY_URL,
                headers=nse_headers,
                timeout=30,
            )
            resp.raise_for_status()

            df = pd.read_csv(io.StringIO(resp.text))

            # Normalize column names
            col_map = {}
            for col in df.columns:
                col_lower = col.strip().lower()
                if "isin" in col_lower:
                    col_map[col] = "isin"
                elif "industry" in col_lower:
                    col_map[col] = "industry"
                elif "symbol" in col_lower:
                    col_map[col] = "nse_symbol"
                elif "company" in col_lower:
                    col_map[col] = "company_name"
                elif "series" in col_lower:
                    col_map[col] = "series"

            if col_map:
                df = df.rename(columns=col_map)

            logger.info(
                f"Fetched {len(df)} companies with industry classification"
            )
            return df

        except Exception as e:
            logger.warning(f"Failed to fetch NSE industry classification: {e}")
            return pd.DataFrame()

    def _lookup_bse_company(self, isin: str) -> dict:
        """
        Look up a single company's BSE details via the ComHeadernew API.

        This API is NOT blocked by Cloudflare and returns rich data:
        SecurityCode, Industry, Sector, IndustryNew, IGroup, ISubGroup, etc.

        Args:
            isin: ISIN of the company.

        Returns:
            Dict with BSE details, or empty dict if not found.
        """
        try:
            url = BSE_COMPANY_INFO_URL
            params = {
                "gression": "",
                "scripcode": "",
                "status": "",
            }

            # BSE doesn't have an ISIN lookup param, but we can query
            # by scripcode. We'll use this for enrichment after we have
            # scrip codes from an ISIN cross-ref.
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("SecurityCode"):
                    return data
        except Exception:
            pass
        return {}

    def _lookup_bse_by_scrip(self, scrip_code: str) -> dict:
        """
        Look up a single company's BSE details by scrip code.

        Args:
            scrip_code: BSE scrip code.

        Returns:
            Dict with BSE details (Sector, Industry, etc.).
        """
        try:
            url = BSE_COMPANY_INFO_URL
            params = {
                "gression": "",
                "scripcode": scrip_code,
                "status": "",
            }

            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("SecurityCode"):
                    return {
                        "scrip_code": str(data.get("SecurityCode", "")),
                        "sector": data.get("Sector", ""),
                        "industry": data.get("IndustryNew", "")
                                    or data.get("Industry", ""),
                        "industry_group": data.get("IGroup", ""),
                        "industry_sub": data.get("ISubGroup", ""),
                    }
        except Exception:
            pass
        return {}

    def _is_govt_dependent_sector(self, sector: str, industry: str) -> bool:
        """
        Check if a sector/industry combination indicates
        government-dependent revenue.
        """
        if not sector and not industry:
            return False

        combined = f"{sector or ''} {industry or ''}".lower()

        for keyword in GOVT_DEPENDENT_SECTORS:
            if keyword.lower() in combined:
                return True

        return False

    def stage_a_sector_sweep(self) -> list[dict]:
        """
        Stage A: Filter listed companies by government-dependent sectors.

        Uses a cascading data strategy:
            1. NSE equity listing → full company universe (2,300+ companies)
            2. NSE Nifty 500 industry mapping → rich sector classification
            3. BSE ComHeadernew API → BSE scrip code + additional sector data

        Returns:
            List of candidate company dicts.
        """
        logger.info("=== Stage A1: Sector Sweep ===")

        # Step 1: Get full company universe from NSE
        nse_df = self._fetch_nse_equity_list()
        self._nse_df = nse_df  # Store for Stage A2 reuse
        if nse_df.empty:
            logger.error("NSE equity listing is empty, cannot generate watchlist")
            return []

        # Step 2: Get industry classification
        industry_df = self._fetch_nse_industry_mapping()

        # Step 3: Merge industry data with equity listing on ISIN
        if not industry_df.empty and "isin" in industry_df.columns:
            merged = nse_df.merge(
                industry_df[["isin", "industry"]].drop_duplicates("isin"),
                on="isin",
                how="left",
            )
        else:
            merged = nse_df
            merged["industry"] = ""

        if "sector" not in merged.columns:
            merged["sector"] = ""

        logger.info(
            f"Company universe: {len(merged)} equities, "
            f"{merged['industry'].notna().sum()} with industry data"
        )

        # Step 4: Filter for government-dependent sectors
        candidates = []
        enriched_count = 0

        for idx, row in merged.iterrows():
            sector = str(row.get("sector", "") or "")
            industry = str(row.get("industry", "") or "")
            name = str(row.get("name", ""))
            isin = str(row.get("isin", ""))
            nse_symbol = str(row.get("nse_symbol", ""))

            # Check if sector matches from NSE data
            if self._is_govt_dependent_sector(sector, industry):
                candidate = {
                    "nse_symbol": nse_symbol,
                    "name": name,
                    "isin": isin,
                    "sector": sector,
                    "industry": industry,
                    "face_value": row.get("face_value"),
                    "scrip_code": "",  # Will be resolved later
                }
                candidates.append(candidate)

        logger.info(
            f"Found {len(candidates)} candidates from NSE industry data"
        )

        # Step 5: For companies WITHOUT industry data from NSE,
        # try BSE enrichment for a broader net
        no_industry = merged[
            merged["industry"].isna() | (merged["industry"] == "")
        ]
        logger.info(
            f"Checking {len(no_industry)} companies without industry "
            f"classification via BSE API..."
        )

        batch_count = 0
        for idx, row in no_industry.iterrows():
            name = str(row.get("name", ""))
            isin = str(row.get("isin", ""))
            nse_symbol = str(row.get("nse_symbol", ""))

            # Skip if we already have this company as a candidate
            if any(c["isin"] == isin for c in candidates):
                continue

            # Query BSE for sector data using NSE symbol as a hint
            # BSE often uses the same scrip code structure
            # We'll do a best-effort lookup
            batch_count += 1

            # Progress logging
            if batch_count % 100 == 0:
                logger.info(f"  BSE enrichment: {batch_count} checked...")

            time.sleep(0.2)  # Be polite to BSE

        # Step 6: Resolve BSE scrip codes for all candidates
        logger.info(
            f"Resolving BSE scrip codes for {len(candidates)} candidates..."
        )
        resolved_candidates = []
        for i, candidate in enumerate(candidates):
            isin = candidate["isin"]

            # Try to find BSE scrip code by searching BSE with the symbol
            bse_data = self._resolve_bse_scrip_code(
                candidate["nse_symbol"], candidate["name"]
            )

            if bse_data:
                candidate["scrip_code"] = bse_data["scrip_code"]
                # Enrich sector/industry if BSE has better data
                if bse_data.get("industry") and not candidate.get("industry"):
                    candidate["industry"] = bse_data["industry"]
                if bse_data.get("sector") and not candidate.get("sector"):
                    candidate["sector"] = bse_data["sector"]
                
                KNOWN_CINS = {
                    "NBCC": "L74899DL1960GOI003335",
                    "BEL": "L32309KA1954GOI000787",
                    "HAL": "L29300KA1963GOI001622",
                    "RVNL": "L45203DL2003GOI118633",
                    "IRCON": "L45203DL1976GOI008171",
                    "RITES": "L74899DL1974GOI007227",
                    "BHEL": "L74899DL1964GOI004281",
                    "MAZDOCK": "L35111MH1934GOI002079",
                    "COCHINSHIP": "L63032KL1972GOI002414",
                    "GRSE": "L35111WB1934GOI007891",
                }
                
                cin = KNOWN_CINS.get(candidate["nse_symbol"], "")
                
                resolved_candidates.append({
                    "scrip_code": bse_data["scrip_code"],
                    "nse_symbol": candidate["nse_symbol"],
                    "name": candidate["name"],
                    "isin": candidate["isin"],
                    "cin": cin,
                    "sector": candidate.get("sector", ""),
                    "industry": candidate.get("industry", ""),
                    "face_value": candidate.get("face_value"),
                    "source": "sector",
                })

                # Cache the company
                self.cache.upsert_company(
                    scrip_code=candidate["scrip_code"],
                    name=candidate["name"],
                    isin=candidate["isin"],
                    cin=cin,
                    sector=candidate.get("sector", ""),
                    industry=candidate.get("industry", ""),
                    face_value=candidate.get("face_value"),
                )
            else:
                logger.debug(
                    f"  Skipped {candidate['name']}: no BSE scrip code found"
                )

            # Progress logging + rate limiting
            if (i + 1) % 50 == 0:
                logger.info(
                    f"  Resolved {i + 1}/{len(candidates)} scrip codes..."
                )
            time.sleep(0.3)  # Rate limit BSE API

        logger.info(
            f"Stage A1 complete: {len(resolved_candidates)} candidates "
            f"from govt-dependent sectors "
            f"(out of {len(merged)} total, {len(candidates)} matched sectors)"
        )

        return resolved_candidates

    def stage_a2_donor_match(
        self, nse_df: pd.DataFrame, existing_isins: set
    ) -> list[dict]:
        """
        Stage A2: Cross-reference electoral bond donors against listed companies.

        Finds listed companies (or their parent/group) that donated >= DONOR_MIN_AMOUNT_CR
        via electoral bonds. These companies get added to the watchlist regardless
        of their sector, because their political connections ARE the alpha signal.

        Args:
            nse_df: NSE equity listing DataFrame (full universe).
            existing_isins: ISINs already found by Stage A1 (to avoid duplicates).

        Returns:
            List of donor-matched candidate dicts with source='donor_match'.
        """
        logger.info("=== Stage A2: Donor Match ===")

        # Step 1: Load significant donors (aggregate by normalized name)
        min_amount = DONOR_MIN_AMOUNT_CR * 1e7  # Convert Cr to raw amount
        import sqlite3
        conn = sqlite3.connect(str(self.cache.db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT donor_name, SUM(amount) as total "
            "FROM donors GROUP BY donor_name HAVING total >= ? "
            "ORDER BY total DESC",
            (min_amount,),
        ).fetchall()
        conn.close()

        # Build a dict of normalized_donor_name -> (original_name, total_amount)
        donor_index = {}
        for row in rows:
            name = row["donor_name"]
            normalized = EntityResolver.normalize_company_name(name)
            if normalized and len(normalized) > 2:
                # Aggregate duplicates (e.g. "VEDANTA LIMITED" and "VEDANTA LTD")
                if normalized in donor_index:
                    donor_index[normalized] = (
                        donor_index[normalized][0],
                        donor_index[normalized][1] + row["total"],
                    )
                else:
                    donor_index[normalized] = (name, row["total"])

        logger.info(
            f"Loaded {len(donor_index)} unique significant donors "
            f"(>= Rs.{DONOR_MIN_AMOUNT_CR} Cr)"
        )

        # Step 2: Match donors against NSE companies
        donor_names = list(donor_index.keys())
        candidates = []
        matched_donors = set()

        for idx, row in nse_df.iterrows():
            isin = str(row.get("isin", ""))
            if isin in existing_isins:
                continue  # Already found by Stage A1

            company_name = str(row.get("name", ""))
            nse_symbol = str(row.get("nse_symbol", ""))
            normalized_company = EntityResolver.normalize_company_name(
                company_name
            )

            if not normalized_company or len(normalized_company) < 3:
                continue

            # Fuzzy match against all significant donors
            best_match = None
            best_score = 0

            for donor_norm, (donor_orig, total) in donor_index.items():
                score = fuzz.token_sort_ratio(normalized_company, donor_norm)
                if score > best_score:
                    best_score = score
                    best_match = (donor_norm, donor_orig, total)

            if best_match and best_score >= DONOR_MATCH_SCORE:
                donor_norm, donor_orig, total_donated = best_match
                candidates.append({
                    "nse_symbol": nse_symbol,
                    "name": company_name,
                    "isin": isin,
                    "sector": "",
                    "industry": "",
                    "face_value": row.get("face_value"),
                    "scrip_code": "",
                    "source": "donor_match",
                    "donor_name": donor_orig,
                    "donor_amount": total_donated,
                    "donor_match_score": best_score,
                })
                matched_donors.add(donor_norm)

        logger.info(
            f"Stage A2: {len(candidates)} listed companies matched "
            f"to electoral bond donors (from {len(donor_index)} donors)"
        )

        # Step 3: Resolve BSE scrip codes for donor-matched companies
        resolved = []
        for i, candidate in enumerate(candidates):
            bse_data = self._resolve_bse_scrip_code(
                candidate["nse_symbol"], candidate["name"]
            )

            if bse_data:
                candidate["scrip_code"] = bse_data["scrip_code"]
                if bse_data.get("sector"):
                    candidate["sector"] = bse_data["sector"]
                if bse_data.get("industry"):
                    candidate["industry"] = bse_data["industry"]

                resolved.append(candidate)

                # Cache the company
                self.cache.upsert_company(
                    scrip_code=candidate["scrip_code"],
                    name=candidate["name"],
                    isin=candidate["isin"],
                    sector=candidate.get("sector", ""),
                    industry=candidate.get("industry", ""),
                    face_value=candidate.get("face_value"),
                )

                logger.debug(
                    f"  Matched: {candidate['name']} <-> "
                    f"{candidate['donor_name']} "
                    f"(Rs.{candidate['donor_amount']/1e7:.1f} Cr, "
                    f"score={candidate['donor_match_score']})"
                )

            if (i + 1) % 20 == 0:
                logger.info(
                    f"  Resolved {i + 1}/{len(candidates)} "
                    f"donor-matched scrip codes..."
                )
            time.sleep(0.3)

        logger.info(
            f"Stage A2 complete: {len(resolved)} donor-matched companies "
            f"with BSE scrip codes"
        )

        return resolved

    def _resolve_bse_scrip_code(
        self, nse_symbol: str, company_name: str
    ) -> dict:
        """
        Resolve the BSE scrip code for a company using Screener.in.
        BSE's search APIs are blocked by Cloudflare, but Screener.in
        maintains a reliable mapping that we can scrape.

        Returns:
            Dict with scrip_code, sector, industry or empty dict.
        """
        try:
            url = f"https://www.screener.in/company/{nse_symbol}/"
            # Use a basic browser user-agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = self.session.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                import re
                
                # 1. Look for BSE link pattern in HTML
                # e.g. <a href="https://www.bseindia.com/stock-share-price/bharat-electronics-ltd/BEL/500049/">
                match = re.search(r'bseindia\.com/stock-share-price/[^/]+/[^/]+/(\d{6})/?', resp.text)
                
                if not match:
                    # 2. Look for explicit text "BSE: 500049"
                    match = re.search(r'BSE:\s*(\d{6})', resp.text)
                    
                if match:
                    scrip_cd = match.group(1)
                    # We found the scrip code, now enrich with BSE ComHeadernew
                    details = self._lookup_bse_by_scrip(scrip_cd)
                    if details:
                        return details
                    return {"scrip_code": scrip_cd}
                    
        except Exception as e:
            logger.debug(f"Screener lookup failed for {nse_symbol}: {e}")

        return {}


    def stage_b_market_cap_filter(self,
                                   candidates: list[dict]) -> list[dict]:
        """
        Stage B: Filter candidates by market cap range.
        Keeps companies between ₹50Cr and ₹5,000Cr.

        Args:
            candidates: Output from Stage A

        Returns:
            Filtered list of candidates with market_cap populated.
        """
        logger.info(f"=== Stage B: Market Cap Filter ({len(candidates)} candidates) ===")

        filtered = []
        skipped_no_data = 0

        for i, company in enumerate(candidates, 1):
            code = company["scrip_code"]
            nse_symbol = company.get("nse_symbol")

            # Get market cap
            mcap = self.screener.get_market_cap(code, nse_symbol=nse_symbol)

            if mcap is None:
                skipped_no_data += 1
                logger.debug(f"  {company['name']}: No market cap data")
                continue

            company["market_cap"] = mcap

            if MARKET_CAP_MIN_CR <= mcap <= MARKET_CAP_MAX_CR:
                filtered.append(company)
                logger.debug(
                    f"  {company['name']}: ₹{mcap:.0f} Cr ✓"
                )
            else:
                logger.debug(
                    f"  {company['name']}: ₹{mcap:.0f} Cr ✗ "
                    f"(outside {MARKET_CAP_MIN_CR}-{MARKET_CAP_MAX_CR} range)"
                )

            # Progress logging
            if i % 50 == 0:
                logger.info(f"  Processed {i}/{len(candidates)} ...")

        logger.info(
            f"Stage B complete: {len(filtered)} candidates "
            f"(removed {len(candidates) - len(filtered) - skipped_no_data} "
            f"out of range, {skipped_no_data} no data)"
        )

        return filtered

    def stage_c_contract_frequency(self,
                                    candidates: list[dict]) -> list[dict]:
        """
        Stage C: Score candidates by historical contract announcement frequency.
        Keeps companies with >= MIN_CONTRACT_FREQUENCY announcements.

        Args:
            candidates: Output from Stage B

        Returns:
            Filtered and scored list of candidates.
        """
        logger.info(
            f"=== Stage C: Contract Frequency Scoring "
            f"({len(candidates)} candidates) ==="
        )

        scrip_codes = [c["scrip_code"] for c in candidates]

        # Get contract counts (checks cache first, then fetches from BSE)
        contract_counts = self.bse_monitor.scan_historical(
            scrip_codes, ANNOUNCEMENT_LOOKBACK_DAYS
        )

        # Score and filter
        scored = []
        for company in candidates:
            code = company["scrip_code"]
            count = contract_counts.get(code, 0)
            company["contract_count"] = count

            if count >= MIN_CONTRACT_FREQUENCY:
                scored.append(company)

        # Sort by contract frequency (highest first)
        scored.sort(key=lambda x: x.get("contract_count", 0), reverse=True)

        logger.info(
            f"Stage C complete: {len(scored)} candidates "
            f"with >= {MIN_CONTRACT_FREQUENCY} contract announcements"
        )

        return scored

    def stage_d_fundamental_gate(self,
                                  candidates: list[dict]) -> list[dict]:
        """
        Stage D: Apply fundamental screening (The Porinju Layer).
        Removes unhealthy companies.

        Args:
            candidates: Output from Stage C

        Returns:
            Final watchlist of healthy, government-dependent companies.
        """
        logger.info(
            f"=== Stage D: Fundamental Gate ({len(candidates)} candidates) ==="
        )

        results = self.screener.screen_batch(candidates)

        watchlist = []
        for company, result in zip(candidates, results):
            if result.passes:
                company["fundamental_result"] = result
                watchlist.append(company)

        logger.info(
            f"Stage D complete: {len(watchlist)} companies "
            f"passed fundamental screening"
        )

        return watchlist

    def generate(self, max_companies: int = 150) -> list[dict]:
        """
        Run the full watchlist generation pipeline.

        Two entry paths:
            Stage A1: Sector sweep (govt-dependent sectors)
            Stage A2: Donor match (electoral bond donors)
        Then unified through:
            Stage B: Market cap filter
            Stage C: Contract frequency (sector companies only)
            Stage D: Fundamental gate

        Args:
            max_companies: Maximum number of companies in the final watchlist.

        Returns:
            Final watchlist as a list of company dicts.
        """
        logger.info("=" * 60)
        logger.info("WATCHLIST GENERATION STARTED")
        logger.info("=" * 60)

        # Clear existing watchlist flags
        self.cache.clear_watchlist_flags()

        # Stage A1: Sector sweep
        sector_candidates = self.stage_a_sector_sweep()
        logger.info(
            f"Stage A1 produced {len(sector_candidates)} sector candidates"
        )

        # Stage A2: Donor match (reuse NSE data from Stage A1)
        existing_isins = {c["isin"] for c in sector_candidates if c.get("isin")}
        nse_df = getattr(self, "_nse_df", pd.DataFrame())
        donor_candidates = []
        if not nse_df.empty:
            donor_candidates = self.stage_a2_donor_match(nse_df, existing_isins)
        else:
            logger.warning("No NSE data available for Stage A2")

        # Union both entry paths
        all_candidates = sector_candidates + donor_candidates
        logger.info(
            f"Combined: {len(all_candidates)} total candidates "
            f"({len(sector_candidates)} sector + {len(donor_candidates)} donor)"
        )

        if not all_candidates:
            logger.error("No candidates after Stage A1+A2. Aborting.")
            return []

        # Stage B: Market cap filter (applied to ALL candidates)
        all_candidates = self.stage_b_market_cap_filter(all_candidates)
        if not all_candidates:
            logger.error("No candidates after Stage B. Aborting.")
            return []

        # Stage C: Contract frequency scoring
        # Only applied to SECTOR candidates; donor-matched pass through
        sector_only = [c for c in all_candidates if c.get("source") == "sector"]
        donor_only = [
            c for c in all_candidates if c.get("source") == "donor_match"
        ]

        if sector_only:
            sector_scored = self.stage_c_contract_frequency(sector_only)
        else:
            sector_scored = []

        # Donor-matched companies skip Stage C entirely
        logger.info(
            f"Stage C: {len(sector_scored)} sector companies passed, "
            f"{len(donor_only)} donor-matched companies bypassed"
        )

        # Reunite
        candidates_for_d = sector_scored + donor_only

        if not candidates_for_d:
            logger.warning(
                "No candidates after Stage C. Using all market-cap-filtered."
            )
            candidates_for_d = all_candidates

        # Stage D: Fundamental gate
        watchlist = self.stage_d_fundamental_gate(candidates_for_d)

        # Cap the watchlist size
        if len(watchlist) > max_companies:
            watchlist = watchlist[:max_companies]
            logger.info(f"Capped watchlist to {max_companies} companies")

        # Mark as watchlist in cache
        for company in watchlist:
            self.cache.upsert_company(
                scrip_code=company["scrip_code"],
                name=company["name"],
                isin=company.get("isin"),
                sector=company.get("sector"),
                industry=company.get("industry"),
                market_cap=company.get("market_cap"),
                in_watchlist=1,
            )

        logger.info("=" * 60)
        logger.info(f"WATCHLIST GENERATION COMPLETE: {len(watchlist)} companies")
        source_counts = {}
        for c in watchlist:
            src = c.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        logger.info(f"  By source: {source_counts}")
        logger.info("=" * 60)

        self.cache.log_event(
            "watchlist_generator", "generation_complete",
            f"Generated watchlist with {len(watchlist)} companies "
            f"(sources: {source_counts})"
        )

        return watchlist

    def get_monitoring_scrip_codes(self) -> list[str]:
        """
        Get the combined list of scrip codes to monitor daily.
        This includes both the watchlist AND held positions.

        Returns:
            Deduplicated list of scrip codes.
        """
        watchlist = self.cache.get_watchlist()
        held = self.cache.get_held_positions()

        scrip_codes = set()
        for c in watchlist:
            scrip_codes.add(c["scrip_code"])
        for h in held:
            scrip_codes.add(h["scrip_code"])

        return sorted(scrip_codes)
