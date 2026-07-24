"""
Shared test fixtures for the Political Alpha Tracker test suite.

Provides an in-memory CacheManager, sample companies, directors,
donors, and announcements that all test modules can reuse.
"""

import os
import pytest
import tempfile
from pathlib import Path

# Override config before importing modules so they use test paths
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

from src.cache_manager import CacheManager


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def cache(tmp_data_dir):
    """Provide a fresh CacheManager backed by a temp SQLite database."""
    db_path = tmp_data_dir / "test_cache.sqlite"
    return CacheManager(db_path=db_path)


@pytest.fixture
def populated_cache(cache):
    """
    CacheManager pre-loaded with sample data for integration tests.

    Companies:
        - RAILCO (540001) — Railway equipment, on watchlist, CIN assigned
        - DEFCO  (540002) — Defence, on watchlist, CIN assigned
        - ROADCO (540003) — Road construction, NOT on watchlist

    Directors:
        - DIN 00000001 (Rajesh Kumar) — on RAILCO + DONORCO (the bridge director)
        - DIN 00000002 (Priya Sharma) — only on RAILCO
        - DIN 00000003 (Amit Singh)   — only on DEFCO

    Donors:
        - DONORCO (CIN: U99999MH2010PLC999999) — donated ₹5 Cr to Prudent Trust, 2025
        - BIGCORP (CIN: U99999DL2005PLC888888) — donated ₹50 Lakh to Prudent Trust, 2024

    Announcements:
        - RAILCO: 3 contract announcements
        - DEFCO:  1 contract announcement + 1 board change
    """
    # ── Companies ──
    cache.upsert_company(
        scrip_code="540001", name="Rail Electrification Co Ltd",
        isin="INE001A01001", cin="L27100MH2000PLC123456",
        sector="Railways", industry="Railway Equipment",
        market_cap=800.0, in_watchlist=1,
    )
    cache.upsert_company(
        scrip_code="540002", name="Defence Components Ltd",
        isin="INE002A01002", cin="L29200DL2005PLC654321",
        sector="Defence", industry="Aerospace & Defence",
        market_cap=1200.0, in_watchlist=1,
    )
    cache.upsert_company(
        scrip_code="540003", name="Highway Builders Corp",
        isin="INE003A01003", cin="L45200MH2010PLC111111",
        sector="Construction", industry="Roads & Highways",
        market_cap=3500.0, in_watchlist=0,
    )

    # ── Directors ──
    # Rajesh Kumar sits on RAILCO *and* DONORCO — this is the bridge
    cache.upsert_directors("L27100MH2000PLC123456", [
        {"din": "00000001", "name": "Rajesh Kumar", "designation": "Managing Director"},
        {"din": "00000002", "name": "Priya Sharma", "designation": "Independent Director"},
    ])
    cache.upsert_directors("L29200DL2005PLC654321", [
        {"din": "00000003", "name": "Amit Singh", "designation": "Director"},
    ])
    # The same Rajesh Kumar also on the donor company board
    cache.upsert_directors("U99999MH2010PLC999999", [
        {"din": "00000001", "name": "Rajesh Kumar", "designation": "Director"},
    ])

    # ── Donors ──
    cache.upsert_donor(
        donor_name="Donor Infrastructure Pvt Ltd",
        donor_cin="U99999MH2010PLC999999",
        amount=50_000_000,  # ₹5 Cr
        year=2025,
        trust_name="Prudent Electoral Trust",
        recipient_party="BJP",
        source="electoral_trust",
    )
    cache.upsert_donor(
        donor_name="Big Corporate Holdings Ltd",
        donor_cin="U99999DL2005PLC888888",
        amount=5_000_000,  # ₹50 Lakh
        year=2024,
        trust_name="Prudent Electoral Trust",
        recipient_party="BJP",
        source="electoral_trust",
    )

    # ── Announcements ──
    cache.insert_announcement(
        scrip_code="540001",
        title="Award of Order worth ₹450 Cr from Indian Railways",
        date="2026-07-10",
        category="Corporate",
        is_contract=True,
    )
    cache.insert_announcement(
        scrip_code="540001",
        title="Tender Award - Supply of transformers to PGCIL",
        date="2026-06-15",
        category="Corporate",
        is_contract=True,
    )
    cache.insert_announcement(
        scrip_code="540001",
        title="New Work Order from Metro Rail Corporation",
        date="2026-03-20",
        category="Corporate",
        is_contract=True,
    )
    cache.insert_announcement(
        scrip_code="540002",
        title="Contract for supply of defence equipment to MoD",
        date="2026-07-05",
        category="Corporate",
        is_contract=True,
    )
    cache.insert_announcement(
        scrip_code="540002",
        title="Appointment of Mr. X as Independent Director",
        date="2026-07-01",
        category="Board Meeting",
        is_board_change=True,
    )

    return cache


# ── Sample data constants for reuse in tests ──

SAMPLE_COMPANIES = [
    {"scrip_code": "540001", "name": "Rail Electrification Co Ltd",
     "cin": "L27100MH2000PLC123456"},
    {"scrip_code": "540002", "name": "Defence Components Ltd",
     "cin": "L29200DL2005PLC654321"},
]

SAMPLE_DIRECTORS = [
    {"din": "00000001", "name": "Rajesh Kumar"},
    {"din": "00000002", "name": "Priya Sharma"},
    {"din": "00000003", "name": "Amit Singh"},
]

BRIDGE_DIRECTOR_DIN = "00000001"  # Rajesh Kumar — the political bridge
DONOR_CIN = "U99999MH2010PLC999999"
RAILCO_CIN = "L27100MH2000PLC123456"
DEFCO_CIN = "L29200DL2005PLC654321"
