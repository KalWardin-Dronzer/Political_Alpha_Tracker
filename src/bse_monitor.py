"""
Political Alpha Tracker — BSE Announcement Monitor

Scrapes BSE India's corporate announcements for watchlist companies.
Detects two event types:
    1. Contract events — new government orders, tenders, LOAs
    2. Board changes  — director appointments/resignations (triggers MCA refresh)

Uses BSE's internal API endpoint (reverse-engineered, unofficial).
Falls back to direct HTML parsing if API changes.
"""

import time
import logging
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    BSE_ANNOUNCEMENTS_URL, BSE_HEADERS, BSE_REQUEST_DELAY,
    CONTRACT_KEYWORDS_PATTERN, BOARD_CHANGE_PATTERN,
    CONTRACT_EXCLUSION_PATTERN, ANNOUNCEMENT_LOOKBACK_DAYS,
)
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


@dataclass
class AnnouncementEvent:
    """Represents a detected BSE announcement event."""
    scrip_code: str
    company_name: str
    title: str
    date: str
    category: str = ""
    event_type: str = ""  # "contract" or "board_change"
    raw_data: dict = field(default_factory=dict)


class BSEMonitor:
    """
    Monitors BSE corporate announcements for a list of scrip codes.

    Usage:
        monitor = BSEMonitor(cache)
        events = monitor.scan_watchlist(scrip_codes)
        contracts = [e for e in events if e.event_type == "contract"]
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update(BSE_HEADERS)

    def _fetch_announcements(self, scrip_code: str,
                              from_date: str, to_date: str,
                              page: int = 1) -> list[dict]:
        """
        Fetch announcements from BSE's internal API for a specific scrip.

        Args:
            scrip_code: BSE scrip code (e.g., "540123")
            from_date: Start date in DD/MM/YYYY format
            to_date: End date in DD/MM/YYYY format
            page: Page number for pagination

        Returns:
            List of announcement dicts from BSE API response.
        """
        params = {
            "pageno": str(page),
            "strCat": "-1",  # All categories
            "strPrevDate": from_date,
            "strScrip": scrip_code,
            "strSearch": "P",  # Previous (date range mode)
            "strToDate": to_date,
            "strType": "C",  # Corporate
        }

        try:
            resp = self.session.get(
                BSE_ANNOUNCEMENTS_URL,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()

            data = resp.json()

            # BSE API returns a JSON object with a "Table" key containing results
            if isinstance(data, dict):
                return data.get("Table", [])
            elif isinstance(data, list):
                return data
            else:
                logger.warning(
                    f"Unexpected BSE API response type for {scrip_code}: "
                    f"{type(data)}"
                )
                return []

        except requests.exceptions.JSONDecodeError:
            logger.warning(
                f"Non-JSON response from BSE API for scrip {scrip_code}. "
                f"Response: {resp.text[:200]}"
            )
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"BSE API request failed for scrip {scrip_code}: {e}")
            return []

    def _classify_announcement(self, title: str) -> Optional[str]:
        """
        Classify an announcement title as contract, board_change, or None.

        Returns:
            "contract", "board_change", or None if not relevant.
        """
        # Check for contract exclusions first (e.g., "NCLT Order")
        if CONTRACT_EXCLUSION_PATTERN.search(title):
            return None

        if CONTRACT_KEYWORDS_PATTERN.search(title):
            return "contract"

        if BOARD_CHANGE_PATTERN.search(title):
            return "board_change"

        return None

    def scan_scrip(self, scrip_code: str,
                   lookback_days: int = 1) -> list[AnnouncementEvent]:
        """
        Scan a single scrip code for relevant announcements.

        Args:
            scrip_code: BSE scrip code
            lookback_days: How many days back to look (1 for daily, 365 for historical)

        Returns:
            List of classified AnnouncementEvent objects.
        """
        to_date = datetime.now().strftime("%Y%m%d")
        from_date = (
            datetime.now() - timedelta(days=lookback_days)
        ).strftime("%Y%m%d")

        all_announcements = []
        page = 1
        max_pages = 5  # Safety limit

        while page <= max_pages:
            batch = self._fetch_announcements(
                scrip_code, from_date, to_date, page
            )
            if not batch:
                break
            all_announcements.extend(batch)
            # BSE typically returns 20 results per page
            if len(batch) < 20:
                break
            page += 1
            time.sleep(BSE_REQUEST_DELAY)

        events = []
        for ann in all_announcements:
            title = ann.get("NEWSSUB", ann.get("NEWS_SUBJECT", ""))
            ann_date = ann.get("NEWS_DT", ann.get("DT_TM", ""))
            category = ann.get("CATEGORYNAME", ann.get("CAT_NAME", ""))
            company_name = ann.get("SLONGNAME", ann.get("COMPANY_NAME", ""))

            # Normalize the date
            try:
                if "T" in ann_date:
                    parsed_date = datetime.fromisoformat(
                        ann_date.replace("Z", "")
                    )
                else:
                    # Try common BSE date formats
                    for fmt in ["%d/%m/%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d"]:
                        try:
                            parsed_date = datetime.strptime(ann_date, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        parsed_date = datetime.now()

                normalized_date = parsed_date.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                normalized_date = datetime.now().strftime("%Y-%m-%d")

            # Classify the announcement
            event_type = self._classify_announcement(title)
            if event_type:
                event = AnnouncementEvent(
                    scrip_code=scrip_code,
                    company_name=company_name,
                    title=title,
                    date=normalized_date,
                    category=category,
                    event_type=event_type,
                    raw_data=ann,
                )
                events.append(event)

                # Cache the announcement
                self.cache.insert_announcement(
                    scrip_code=scrip_code,
                    title=title,
                    date=normalized_date,
                    category=category,
                    is_contract=(event_type == "contract"),
                    is_board_change=(event_type == "board_change"),
                )

        return events

    def scan_watchlist(self, scrip_codes: list[str],
                       lookback_days: int = 1) -> list[AnnouncementEvent]:
        """
        Scan all watchlist scrip codes for relevant announcements.

        Args:
            scrip_codes: List of BSE scrip codes to monitor
            lookback_days: How many days back to scan

        Returns:
            List of all detected events across the watchlist.
        """
        all_events = []
        total = len(scrip_codes)

        for i, code in enumerate(scrip_codes, 1):
            logger.info(
                f"Scanning BSE announcements for {code} ({i}/{total})"
            )
            try:
                events = self.scan_scrip(code, lookback_days)
                all_events.extend(events)

                if events:
                    contracts = [e for e in events if e.event_type == "contract"]
                    board_changes = [
                        e for e in events if e.event_type == "board_change"
                    ]
                    logger.info(
                        f"  {code}: {len(contracts)} contracts, "
                        f"{len(board_changes)} board changes"
                    )
            except Exception as e:
                logger.error(f"  Error scanning {code}: {e}")
                self.cache.log_event(
                    "bse_monitor", "scan_error",
                    f"Failed to scan {code}: {e}", "ERROR"
                )

            # Rate limit between scrips
            if i < total:
                time.sleep(BSE_REQUEST_DELAY)

        # Log summary
        contracts = [e for e in all_events if e.event_type == "contract"]
        board_changes = [e for e in all_events if e.event_type == "board_change"]
        self.cache.log_event(
            "bse_monitor", "scan_complete",
            f"Scanned {total} scrips: "
            f"{len(contracts)} contracts, {len(board_changes)} board changes"
        )

        # Heartbeat check: if no announcements at all, it might be a BSE issue
        if total > 0 and len(all_events) == 0 and lookback_days <= 3:
            logger.warning(
                "Zero announcements found across entire watchlist — "
                "possible BSE API issue"
            )
            self.cache.log_event(
                "bse_monitor", "zero_announcements",
                "No announcements found for any watchlist scrip. "
                "BSE API may be down or changed.",
                "WARNING"
            )

        return all_events

    def scan_historical(self, scrip_codes: list[str],
                         lookback_days: int = None) -> dict[str, int]:
        """
        Scan historical announcements for contract frequency scoring.
        Used by watchlist_generator to rank companies by government activity.

        Args:
            scrip_codes: List of BSE scrip codes
            lookback_days: Override for lookback period

        Returns:
            Dict mapping scrip_code -> contract announcement count.
        """
        lookback = lookback_days or ANNOUNCEMENT_LOOKBACK_DAYS
        contract_counts = {}

        for i, code in enumerate(scrip_codes, 1):
            # Check cache first
            cached_count = self.cache.get_contract_announcement_count(
                code, lookback
            )
            if cached_count > 0:
                contract_counts[code] = cached_count
                logger.debug(f"  {code}: {cached_count} contracts (cached)")
                continue

            # Fetch from BSE
            logger.info(
                f"Historical scan for {code} ({i}/{len(scrip_codes)})"
            )
            try:
                events = self.scan_scrip(code, lookback)
                count = len(
                    [e for e in events if e.event_type == "contract"]
                )
                contract_counts[code] = count
            except Exception as e:
                logger.error(f"  Error scanning history for {code}: {e}")
                contract_counts[code] = 0

            # Rate limit
            time.sleep(BSE_REQUEST_DELAY)

        return contract_counts
