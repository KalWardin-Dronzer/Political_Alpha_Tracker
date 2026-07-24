"""
Political Alpha Tracker — Donor Ingester

Ingests Electoral Trust and Electoral Bond donor data from multiple sources
using a cascading fallback strategy:

    1. ECI contribution reports (Excel) — most structured
    2. MyNeta HTML tables — well-formatted, scrape-friendly
    3. ADR PDF reports via tabula-py — last resort
    4. Electoral Bond CSV (one-time SBI disclosure load)

All donor records are stored in the SQLite cache and linked to CINs
via the EntityResolver.
"""

import io
import re
import time
import logging
import csv
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.config import (
    MYNETA_TRUST_URL, ECI_TRUST_URL, MYNETA_REQUEST_DELAY,
    BSE_HEADERS, ELECTORAL_BONDS_PURCHASE_FILE, ELECTORAL_BONDS_ENCASHMENT_FILE,
)
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)

# Common amount parsing patterns
AMOUNT_PATTERN = re.compile(r"[\d,]+(?:\.\d+)?")
CRORE_PATTERN = re.compile(r"(?i)(\d[\d,]*(?:\.\d+)?)\s*(?:cr(?:ore)?|crores?)")
LAKH_PATTERN = re.compile(r"(?i)(\d[\d,]*(?:\.\d+)?)\s*(?:lakh|lakhs?|lac)")


def parse_amount(amount_str: str) -> Optional[float]:
    """
    Parse an Indian-format amount string to float (in Rupees).

    Handles formats like:
        "5,20,00,000" -> 52000000
        "52.5 Crore" -> 525000000
        "₹ 10,00,000" -> 1000000
        "5.2 Cr" -> 52000000
    """
    if not amount_str:
        return None

    amount_str = str(amount_str).strip().replace("₹", "").strip()

    # Try Crore format first
    crore_match = CRORE_PATTERN.search(amount_str)
    if crore_match:
        val = float(crore_match.group(1).replace(",", ""))
        return val * 1e7  # 1 Crore = 10 million

    # Try Lakh format
    lakh_match = LAKH_PATTERN.search(amount_str)
    if lakh_match:
        val = float(lakh_match.group(1).replace(",", ""))
        return val * 1e5  # 1 Lakh = 100,000

    # Try raw number
    amount_match = AMOUNT_PATTERN.search(amount_str)
    if amount_match:
        val_str = amount_match.group().replace(",", "")
        try:
            return float(val_str)
        except ValueError:
            pass

    return None


class DonorIngester:
    """
    Ingests political donor data from multiple sources.

    Usage:
        ingester = DonorIngester(cache)
        count = ingester.ingest_all()
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": BSE_HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        })

    def ingest_electoral_bonds(
        self,
        purchase_path: Path = None,
        encashment_path: Path = None,
    ) -> int:
        """
        Load Electoral Bond data from the SBI disclosure CSVs.
        One-time load — the scheme is dead, so this data is static.

        The SBI disclosure comes as TWO files:
            PurchaseData.csv:    Date of Purchase, Purchaser Name, Denomination
            EncashmentData.csv:  Date of Encashment, Name of the Political Party, Denomination

        Since bonds are anonymous (no serial number linking purchaser→party),
        we ingest the Purchase side (who donated) as donor records. The
        Encashment side is used to build a reference of which parties received
        how much, but the purchaser-to-party link is not directly available.

        Args:
            purchase_path: Path to PurchaseData.csv
            encashment_path: Path to EncashmentData.csv

        Returns:
            Number of donor records loaded.
        """
        purchase_file = purchase_path or ELECTORAL_BONDS_PURCHASE_FILE
        encashment_file = encashment_path or ELECTORAL_BONDS_ENCASHMENT_FILE

        # ── Step 1: Load encashment data (party reference) ──
        party_totals = {}
        if encashment_file.exists():
            logger.info(f"Loading encashment data from {encashment_file}")
            try:
                with open(encashment_file, "r", encoding="utf-8-sig") as f:
                    raw = f.read()

                # Fix multi-line header: "Date of\nEncashment" → single line
                # The first header field spans two lines in the raw CSV
                raw = raw.replace('"Date of\nEncashment"', 'Date of Encashment')

                reader = csv.DictReader(io.StringIO(raw))

                for row in reader:
                    party = (
                        row.get("Name of the Political Party")
                        or ""
                    ).strip()

                    denom_str = (
                        row.get("Denomination")
                        or ""
                    ).strip()

                    if party and denom_str:
                        amount = parse_amount(denom_str)
                        if amount:
                            party_totals[party] = party_totals.get(party, 0) + amount

                logger.info(
                    f"Loaded encashment data: {len(party_totals)} parties, "
                    f"top receiver: {max(party_totals, key=party_totals.get) if party_totals else 'N/A'}"
                )
            except Exception as e:
                logger.error(f"Failed to load encashment data: {e}")
        else:
            logger.warning(f"Encashment file not found at {encashment_file}")

        # ── Step 2: Load purchase data (the donors — this is what we need) ──
        if not purchase_file.exists():
            logger.warning(
                f"Electoral bonds purchase file not found at {purchase_file}. "
                f"Skipping bond data load."
            )
            return 0

        logger.info(f"Loading Electoral Bond purchase data from {purchase_file}")
        count = 0

        try:
            with open(purchase_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    purchaser = (
                        row.get("Purchaser Name")
                        or row.get("purchaser_name")
                        or ""
                    ).strip()

                    denom_str = (
                        row.get("Denomination")
                        or row.get("denomination")
                        or ""
                    ).strip()

                    purchase_date = (
                        row.get("Date of Purchase")
                        or row.get("purchase_date")
                        or ""
                    ).strip()

                    if not purchaser or not denom_str:
                        continue

                    amount = parse_amount(denom_str)
                    if not amount:
                        continue

                    # Parse year from DD-Mon-YY format (e.g., "12-Apr-19")
                    year = self._parse_bond_date_year(purchase_date)
                    if not year:
                        year = 2023  # Safe default

                    self.cache.upsert_donor(
                        donor_name=purchaser,
                        amount=amount,
                        year=year,
                        trust_name="Electoral Bonds",
                        recipient_party=None,  # Not linkable from SBI data
                        source="electoral_bond",
                    )
                    count += 1

        except Exception as e:
            logger.error(f"Failed to load electoral bonds CSV: {e}")

        logger.info(f"Loaded {count} Electoral Bond records from {count} rows")
        self.cache.log_event(
            "donor_ingester", "bonds_loaded",
            f"Loaded {count} Electoral Bond records from {purchase_file}. "
            f"Encashment parties: {len(party_totals)}"
        )

        return count

    @staticmethod
    def _parse_bond_date_year(date_str: str) -> Optional[int]:
        """
        Parse year from SBI disclosure date format.

        Handles:
            "12-Apr-19" → 2019
            "03-Oct-23" → 2023
            "2024-01-15" → 2024

        Returns:
            4-digit year or None.
        """
        if not date_str:
            return None

        # Try DD-Mon-YY format first (the SBI format)
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str.strip(), "%d-%b-%y")
            return dt.year
        except ValueError:
            pass

        # Fallback: extract any 4-digit year
        year_match = re.search(r"20\d{2}", date_str)
        if year_match:
            return int(year_match.group())

        # Fallback: 2-digit year at end
        yy_match = re.search(r"-(\d{2})$", date_str)
        if yy_match:
            yy = int(yy_match.group(1))
            return 2000 + yy

        return None

    def ingest_from_myneta(self) -> int:
        """
        Scrape Electoral Trust donor data from MyNeta.info.
        MyNeta presents trust data in structured HTML tables.

        Returns:
            Number of donor records ingested.
        """
        logger.info("Attempting to fetch Electoral Trust data from MyNeta...")
        count = 0

        try:
            resp = self.session.get(MYNETA_TRUST_URL, timeout=30)
            resp.raise_for_status()
            time.sleep(MYNETA_REQUEST_DELAY)

            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for data tables
            tables = soup.find_all("table")

            for table in tables:
                headers = [
                    th.get_text(strip=True).lower()
                    for th in table.find_all("th")
                ]

                # Identify relevant columns
                donor_col = None
                amount_col = None
                party_col = None
                trust_col = None

                for i, h in enumerate(headers):
                    if any(k in h for k in ["donor", "contributor", "company"]):
                        donor_col = i
                    elif any(k in h for k in ["amount", "contribution", "rs"]):
                        amount_col = i
                    elif any(k in h for k in ["party", "recipient"]):
                        party_col = i
                    elif any(k in h for k in ["trust", "electoral trust"]):
                        trust_col = i

                if donor_col is None or amount_col is None:
                    continue

                rows = table.find_all("tr")[1:]  # Skip header
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) <= max(donor_col, amount_col):
                        continue

                    donor_name = cells[donor_col].get_text(strip=True)
                    amount_str = cells[amount_col].get_text(strip=True)
                    amount = parse_amount(amount_str)

                    if not donor_name or not amount:
                        continue

                    party = ""
                    if party_col is not None and len(cells) > party_col:
                        party = cells[party_col].get_text(strip=True)

                    trust_name = ""
                    if trust_col is not None and len(cells) > trust_col:
                        trust_name = cells[trust_col].get_text(strip=True)

                    # Default year to current FY
                    from datetime import datetime
                    current_year = datetime.now().year

                    self.cache.upsert_donor(
                        donor_name=donor_name,
                        amount=amount,
                        year=current_year,
                        trust_name=trust_name,
                        recipient_party=party,
                        source="myneta",
                    )
                    count += 1

        except requests.exceptions.RequestException as e:
            logger.warning(f"MyNeta scraping failed: {e}")
        except Exception as e:
            logger.error(f"Error parsing MyNeta data: {e}")

        if count > 0:
            logger.info(f"Ingested {count} donor records from MyNeta")
        else:
            logger.warning("No donor data extracted from MyNeta")

        return count

    def ingest_from_eci_excel(self) -> int:
        """
        Attempt to download and parse ECI contribution reports (Excel format).
        ECI sometimes publishes trust reports as .xlsx files.

        Returns:
            Number of donor records ingested.
        """
        logger.info("Attempting to fetch Electoral Trust data from ECI...")
        count = 0

        try:
            # The ECI URL structure varies — try to find downloadable reports
            resp = self.session.get(ECI_TRUST_URL, timeout=30)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for Excel/PDF download links
            download_links = []
            for link in soup.find_all("a", href=True):
                href = link["href"].lower()
                text = link.get_text(strip=True).lower()

                if any(ext in href for ext in [".xlsx", ".xls"]):
                    if "trust" in text or "contribution" in text:
                        download_links.append(link["href"])

            for dl_url in download_links[:3]:  # Try first 3 links
                try:
                    if not dl_url.startswith("http"):
                        dl_url = f"https://www.eci.gov.in{dl_url}"

                    file_resp = self.session.get(dl_url, timeout=30)
                    file_resp.raise_for_status()

                    # Parse with openpyxl via pandas
                    import pandas as pd
                    df = pd.read_excel(
                        io.BytesIO(file_resp.content),
                        engine="openpyxl",
                    )

                    # Try to identify columns
                    for _, row_data in df.iterrows():
                        values = [str(v).strip() for v in row_data.values if pd.notna(v)]
                        # Simple heuristic: look for rows with a name and a number
                        name_candidates = [
                            v for v in values
                            if len(v) > 5 and not v.replace(",", "").replace(".", "").isdigit()
                        ]
                        amount_candidates = [
                            parse_amount(v) for v in values
                        ]
                        amount_candidates = [a for a in amount_candidates if a and a > 10000]

                        if name_candidates and amount_candidates:
                            from datetime import datetime
                            self.cache.upsert_donor(
                                donor_name=name_candidates[0],
                                amount=amount_candidates[0],
                                year=datetime.now().year,
                                source="eci_excel",
                            )
                            count += 1

                    time.sleep(MYNETA_REQUEST_DELAY)

                except Exception as e:
                    logger.debug(f"Failed to parse ECI Excel from {dl_url}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"ECI data fetch failed: {e}")

        if count > 0:
            logger.info(f"Ingested {count} donor records from ECI Excel")
        else:
            logger.info("No donor data extracted from ECI Excel")

        return count

    def ingest_from_pdf(self, pdf_path: Path = None) -> int:
        """
        Last-resort: Extract donor data from ADR PDF reports using tabula-py.

        Args:
            pdf_path: Path to a local PDF file (if already downloaded).

        Returns:
            Number of donor records ingested.
        """
        count = 0

        try:
            import tabula

            if pdf_path and pdf_path.exists():
                logger.info(f"Extracting tables from PDF: {pdf_path}")

                # Extract all tables from the PDF
                tables = tabula.read_pdf(
                    str(pdf_path),
                    pages="all",
                    multiple_tables=True,
                    pandas_options={"header": None},
                )

                for table_df in tables:
                    if table_df.empty or len(table_df.columns) < 2:
                        continue

                    for _, row_data in table_df.iterrows():
                        values = [
                            str(v).strip()
                            for v in row_data.values
                            if str(v).strip() and str(v).strip().lower() != "nan"
                        ]

                        name_candidates = [
                            v for v in values
                            if len(v) > 5
                            and not v.replace(",", "").replace(".", "").isdigit()
                        ]
                        amount_candidates = [
                            parse_amount(v)
                            for v in values
                        ]
                        amount_candidates = [
                            a for a in amount_candidates if a and a > 10000
                        ]

                        if name_candidates and amount_candidates:
                            from datetime import datetime
                            self.cache.upsert_donor(
                                donor_name=name_candidates[0],
                                amount=amount_candidates[0],
                                year=datetime.now().year,
                                source="adr_pdf",
                            )
                            count += 1

        except ImportError:
            logger.warning(
                "tabula-py not installed or Java not available. "
                "PDF extraction skipped."
            )
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")

        if count > 0:
            logger.info(f"Ingested {count} donor records from PDF")

        return count

    def ingest_all(self) -> int:
        """
        Run the full cascading ingestion pipeline.
        Tries each source in order, accumulating donor records.

        Returns:
            Total number of donor records ingested.
        """
        total = 0

        # 1. Load Electoral Bond data (one-time static load)
        existing_bonds = self.cache.get_donors(min_year=2018)
        bond_sources = [d for d in existing_bonds if d.get("source") == "electoral_bond"]
        if not bond_sources:
            total += self.ingest_electoral_bonds()

        # 2. Try ECI Excel (most structured)
        eci_count = self.ingest_from_eci_excel()
        total += eci_count

        # 3. If ECI didn't yield enough, try MyNeta
        if eci_count < 50:
            myneta_count = self.ingest_from_myneta()
            total += myneta_count

        # 4. If still sparse, try PDF fallback
        if total < 50:
            # Check for any local PDF files in the data directory
            from src.config import DATA_DIR
            for pdf_file in DATA_DIR.glob("*.pdf"):
                if "trust" in pdf_file.name.lower() or "adr" in pdf_file.name.lower():
                    total += self.ingest_from_pdf(pdf_file)

        # Log final summary
        all_donors = self.cache.get_donors()
        sources = {}
        for d in all_donors:
            src = d.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1

        self.cache.log_event(
            "donor_ingester", "ingestion_complete",
            f"Total donors in DB: {len(all_donors)}. "
            f"Sources: {sources}"
        )

        logger.info(
            f"Donor ingestion complete. "
            f"Total records: {len(all_donors)}, "
            f"Sources: {sources}"
        )

        return total
