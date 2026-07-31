"""
Political Alpha Tracker — MCA Director Resolver

Resolves a company's board of directors using MCA (Ministry of Corporate Affairs)
public data. Extracts Director Identification Numbers (DINs) which serve as the
canonical graph join key for mapping political connections.

Data Source Strategy:
    1. Check SQLite cache (90-day TTL)
    2. Scrape MCA V3 portal's public company master page
    3. Fallback: Zaubacorp.com (free MCA data aggregator)
    4. Fallback: data.gov.in API (if available)
"""

import re
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.config import (
    MCA_COMPANY_SEARCH_URL, MCA_HEADERS, MCA_REQUEST_DELAY,
    MCA_CACHE_TTL_DAYS,
    ZAUBACORP_BASE_URL, ZAUBACORP_HEADERS, ZAUBACORP_REQUEST_DELAY,
)
from dataclasses import dataclass

from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


@dataclass
class DirectorRecord:
    """Represents a company director."""
    din: str
    name: str
    designation: str = ""
    cin: str = ""


class MCAResolver:
    """
    Resolves company directors from MCA public data.

    Usage:
        resolver = MCAResolver(cache)
        directors = resolver.resolve_directors("L12345MH2000PLC123456")
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update(MCA_HEADERS)

    def resolve_directors(self, cin: str,
                          force_refresh: bool = False) -> list[DirectorRecord]:
        """
        Get the board of directors for a company identified by CIN.

        Args:
            cin: Corporate Identification Number
            force_refresh: Skip cache and fetch fresh data

        Returns:
            List of DirectorRecord objects.
        """
        # Step 1: Check cache
        if not force_refresh and self.cache.is_director_cache_fresh(
            cin, MCA_CACHE_TTL_DAYS
        ):
            cached = self.cache.get_directors_for_company(cin)
            if cached:
                logger.debug(f"Using cached directors for {cin} ({len(cached)} found)")
                return [
                    DirectorRecord(
                        din=d["din"],
                        name=d["name"],
                        designation=d.get("designation", ""),
                        cin=cin,
                    )
                    for d in cached
                ]

        # Step 2: Scrape MCA V3 portal
        logger.info(f"Fetching directors from MCA for CIN: {cin}")
        directors = self._scrape_mca_portal(cin)

        if not directors:
            # Step 3: Fallback to Zaubacorp.com
            logger.info(f"MCA portal failed, trying Zaubacorp for {cin}")
            directors = self._scrape_zaubacorp(cin)

        if not directors:
            # Step 4: Fallback to data.gov.in API
            logger.info(f"Zaubacorp failed, trying data.gov.in for {cin}")
            directors = self._query_data_gov_api(cin)

        if directors:
            # Phase 5: Resolve Deep State Bureaucrats
            company_name = "Company"
            company = self.cache.get_company_by_cin(cin)
            if company:
                company_name = company.get("name", "Company")
            
            from src.bureaucrat_resolver import BureaucratResolver
            resolver = BureaucratResolver()
            
            directors_dicts = [
                {
                    "din": d.din,
                    "name": d.name,
                    "designation": d.designation,
                }
                for d in directors
            ]
            
            directors_dicts = resolver.check_bureaucrats(company_name, directors_dicts)

            # Cache the results
            self.cache.upsert_directors(cin, directors_dicts)
            logger.info(f"Resolved {len(directors)} directors for {cin}")
        else:
            logger.warning(f"Could not resolve directors for CIN: {cin}")
            self.cache.log_event(
                "mca_resolver", "resolution_failed",
                f"Failed to resolve directors for CIN: {cin}", "WARNING"
            )

        return directors

    def _scrape_mca_portal(self, cin: str) -> list[DirectorRecord]:
        """
        Scrape director data from MCA V3 portal's public company page.

        The MCA portal allows searching company master data by CIN without
        login. The response includes a table of directors with DINs.
        """
        directors = []

        try:
            # MCA V3 uses a form-based search. We need to:
            # 1. GET the search page to establish a session
            # 2. POST the search form with the CIN
            # 3. Parse the results page

            # Establish session
            self.session.get(
                "https://www.mca.gov.in/mcafoportal/showCompanyMasterData.do",
                timeout=30,
            )
            time.sleep(1)

            # Submit search
            search_data = {
                "companyName": "",
                "CIN": cin,
                "companyType": "",
                "State": "",
                "SRN": "",
            }

            resp = self.session.post(
                MCA_COMPANY_SEARCH_URL,
                data=search_data,
                timeout=30,
            )
            resp.raise_for_status()
            time.sleep(MCA_REQUEST_DELAY)

            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for director information in the response
            # MCA portal typically has a section with director details
            # containing DIN and Name in table rows

            # Strategy 1: Find table with "DIN" header
            tables = soup.find_all("table")
            for table in tables:
                headers = [
                    th.get_text(strip=True).upper()
                    for th in table.find_all("th")
                ]
                if "DIN" in headers or "DIN/DPIN" in headers:
                    din_idx = next(
                        i for i, h in enumerate(headers) if "DIN" in h
                    )
                    name_idx = next(
                        (i for i, h in enumerate(headers) if "NAME" in h),
                        din_idx + 1
                    )
                    desig_idx = next(
                        (i for i, h in enumerate(headers)
                         if "DESIGNATION" in h or "POSITION" in h),
                        None,
                    )

                    for row in table.find_all("tr")[1:]:  # Skip header row
                        cells = row.find_all("td")
                        if len(cells) > max(din_idx, name_idx):
                            din = cells[din_idx].get_text(strip=True)
                            name = cells[name_idx].get_text(strip=True)
                            designation = ""
                            if desig_idx is not None and len(cells) > desig_idx:
                                designation = cells[desig_idx].get_text(
                                    strip=True
                                )

                            # Validate DIN format (8 digits)
                            if re.match(r"^\d{7,8}$", din):
                                directors.append(DirectorRecord(
                                    din=din.zfill(8),  # Pad to 8 digits
                                    name=name.title(),
                                    designation=designation,
                                    cin=cin,
                                ))
                    break  # Found the right table

            # Strategy 2: Look for DIN patterns in the HTML text
            if not directors:
                # Sometimes DINs appear in specific div/span elements
                text = soup.get_text()
                din_pattern = re.compile(
                    r"(?:DIN|Director.*?Identification)\s*[:\-]?\s*(\d{7,8})"
                )
                din_matches = din_pattern.findall(text)

                # Also try to find associated names
                # Look for patterns like "Name: John Doe, DIN: 12345678"
                name_din_pattern = re.compile(
                    r"(?:Name|Director)\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
                    r".*?DIN\s*[:\-]?\s*(\d{7,8})",
                    re.DOTALL,
                )
                for match in name_din_pattern.finditer(text):
                    directors.append(DirectorRecord(
                        din=match.group(2).zfill(8),
                        name=match.group(1).title(),
                        cin=cin,
                    ))

                # If we only found DINs without names, still record them
                if not directors and din_matches:
                    for din in set(din_matches):
                        directors.append(DirectorRecord(
                            din=din.zfill(8),
                            name="Unknown",
                            cin=cin,
                        ))

        except requests.exceptions.RequestException as e:
            logger.error(f"MCA portal request failed for {cin}: {e}")
        except Exception as e:
            logger.error(f"Error parsing MCA portal response for {cin}: {e}")

        return directors

    def _scrape_zaubacorp(self, cin: str) -> list[DirectorRecord]:
        """
        Scrape director data from Zaubacorp.com, a free MCA data aggregator.

        Zaubacorp exposes structured tables with DIN, Name, Designation,
        End Date, and Appointment Date for all current and past directors.
        We filter to only current directors (End Date == '-').
        """
        directors = []

        try:
            # Build the URL: /company/<COMPANY-NAME-SLUG>/<CIN>
            # The company name slug is optional; Zaubacorp redirects by CIN.
            url = f"{ZAUBACORP_BASE_URL}/-/{cin}"

            resp = requests.get(
                url,
                headers=ZAUBACORP_HEADERS,
                timeout=20,
                allow_redirects=True,
            )
            resp.raise_for_status()
            time.sleep(ZAUBACORP_REQUEST_DELAY)

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find the directors table: it has headers with "DIN" column
            all_tables = soup.find_all("table")
            for table in all_tables:
                headers = [
                    th.get_text(strip=True).upper()
                    for th in table.find_all("th")
                ]

                # The director table has columns:
                # DIN | Name | Designation | End Date | Appointment Date
                if "DIN" not in headers:
                    continue

                din_idx = next(i for i, h in enumerate(headers) if h == "DIN")
                name_idx = next(
                    (i for i, h in enumerate(headers)
                     if "NAME" in h),
                    din_idx + 1
                )
                desig_idx = next(
                    (i for i, h in enumerate(headers)
                     if "DESIGNATION" in h),
                    None
                )
                end_date_idx = next(
                    (i for i, h in enumerate(headers)
                     if "END" in h and "DATE" in h),
                    None
                )

                for row in table.find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if len(cells) <= max(din_idx, name_idx):
                        continue

                    din_text = cells[din_idx].get_text(strip=True)
                    name_text = cells[name_idx].get_text(strip=True)

                    # Validate DIN (7-8 digit number)
                    if not re.match(r"^\d{7,8}$", din_text):
                        continue

                    # Filter: only current directors (End Date == '-' or empty)
                    if end_date_idx is not None and len(cells) > end_date_idx:
                        end_date = cells[end_date_idx].get_text(strip=True)
                        if end_date and end_date != "-":
                            continue  # Director has left the board

                    designation = ""
                    if desig_idx is not None and len(cells) > desig_idx:
                        designation = cells[desig_idx].get_text(strip=True)

                    directors.append(DirectorRecord(
                        din=din_text.zfill(8),
                        name=name_text.title(),
                        designation=designation,
                        cin=cin,
                    ))

                if directors:
                    break  # Found the right table

            if directors:
                logger.info(
                    f"Zaubacorp: found {len(directors)} current directors "
                    f"for CIN {cin}"
                )
            else:
                logger.warning(f"Zaubacorp: no directors found for CIN {cin}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Zaubacorp request failed for {cin}: {e}")
        except Exception as e:
            logger.error(f"Error parsing Zaubacorp response for {cin}: {e}")

        return directors

    def _query_data_gov_api(self, cin: str) -> list[DirectorRecord]:
        """
        Query data.gov.in MCA API as a fallback.
        This API is unreliable but sometimes works.
        """
        directors = []
        api_url = (
            "https://api.data.gov.in/resource/"
            "abfcb26c-53e0-4c52-88c6-7e5b75e2a098"  # MCA Director dataset
        )

        try:
            params = {
                "api-key": "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b",
                "format": "json",
                "filters[CIN]": cin,
                "limit": 50,
            }

            resp = requests.get(api_url, params=params, timeout=30)
            resp.raise_for_status()
            time.sleep(MCA_REQUEST_DELAY)

            data = resp.json()
            records = data.get("records", [])

            for record in records:
                din = record.get("din", record.get("DIN", ""))
                name = record.get(
                    "director_name",
                    record.get("DIRECTOR_NAME", "Unknown")
                )
                designation = record.get(
                    "designation",
                    record.get("DESIGNATION", "")
                )

                if din and re.match(r"^\d{7,8}$", str(din)):
                    directors.append(DirectorRecord(
                        din=str(din).zfill(8),
                        name=name.title() if name else "Unknown",
                        designation=designation,
                        cin=cin,
                    ))

        except Exception as e:
            logger.error(f"data.gov.in API failed for {cin}: {e}")

        return directors

    def resolve_batch(self, cins: list[str],
                      force_refresh: bool = False) -> dict[str, list[DirectorRecord]]:
        """
        Resolve directors for multiple companies.

        Args:
            cins: List of CINs to resolve
            force_refresh: Skip cache for all

        Returns:
            Dict mapping CIN -> list of DirectorRecords
        """
        results = {}
        total = len(cins)

        for i, cin in enumerate(cins, 1):
            logger.info(f"Resolving directors {i}/{total}: {cin}")
            directors = self.resolve_directors(cin, force_refresh)
            results[cin] = directors

            # Rate limit between companies
            if i < total:
                time.sleep(MCA_REQUEST_DELAY)

        resolved = sum(1 for ds in results.values() if ds)
        self.cache.log_event(
            "mca_resolver", "batch_complete",
            f"Resolved directors for {resolved}/{total} companies"
        )

        return results
