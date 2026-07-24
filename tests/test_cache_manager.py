"""
Tests for CacheManager — the SQLite caching layer.

Covers: table creation, CRUD for companies/directors/donors/announcements,
TTL freshness checks, held positions lifecycle, and system logging.
"""

import pytest
from datetime import datetime, timedelta

from tests.conftest import RAILCO_CIN, DEFCO_CIN, BRIDGE_DIRECTOR_DIN, DONOR_CIN


class TestCompanyOperations:
    """Tests for company CRUD operations."""

    def test_upsert_and_get_company(self, cache):
        cache.upsert_company(
            scrip_code="500100", name="Test Company Ltd",
            isin="INE100A01001", cin="L10000MH2020PLC000001",
            sector="IT", market_cap=500.0,
        )
        company = cache.get_company("500100")
        assert company is not None
        assert company["name"] == "Test Company Ltd"
        assert company["cin"] == "L10000MH2020PLC000001"
        assert company["market_cap"] == 500.0

    def test_upsert_preserves_existing_fields(self, cache):
        """COALESCE should keep old CIN if new value is None."""
        cache.upsert_company(scrip_code="500200", name="ABC Ltd",
                              cin="L99999MH2000PLC999999")
        cache.upsert_company(scrip_code="500200", name="ABC Ltd",
                              cin=None, market_cap=1000.0)
        company = cache.get_company("500200")
        assert company["cin"] == "L99999MH2000PLC999999"
        assert company["market_cap"] == 1000.0

    def test_get_nonexistent_company(self, cache):
        assert cache.get_company("999999") is None

    def test_get_company_by_cin(self, populated_cache):
        company = populated_cache.get_company_by_cin(RAILCO_CIN)
        assert company is not None
        assert company["scrip_code"] == "540001"

    def test_get_watchlist(self, populated_cache):
        watchlist = populated_cache.get_watchlist()
        assert len(watchlist) == 2
        codes = {c["scrip_code"] for c in watchlist}
        assert codes == {"540001", "540002"}

    def test_clear_watchlist_flags(self, populated_cache):
        populated_cache.clear_watchlist_flags()
        watchlist = populated_cache.get_watchlist()
        assert len(watchlist) == 0

    def test_get_all_companies(self, populated_cache):
        all_companies = populated_cache.get_all_companies()
        assert len(all_companies) == 3


class TestDirectorOperations:
    """Tests for director CRUD and cross-referencing."""

    def test_upsert_and_get_directors(self, populated_cache):
        directors = populated_cache.get_directors_for_company(RAILCO_CIN)
        assert len(directors) == 2
        dins = {d["din"] for d in directors}
        assert "00000001" in dins
        assert "00000002" in dins

    def test_get_all_companies_for_director(self, populated_cache):
        """Rajesh Kumar (00000001) should be on RAILCO + DONORCO boards."""
        boards = populated_cache.get_all_companies_for_director(
            BRIDGE_DIRECTOR_DIN
        )
        assert len(boards) == 2
        cins = {b["cin"] for b in boards}
        assert RAILCO_CIN in cins
        assert DONOR_CIN in cins

    def test_director_cache_freshness(self, populated_cache):
        assert populated_cache.is_director_cache_fresh(RAILCO_CIN, 90) is True
        assert populated_cache.is_director_cache_fresh(RAILCO_CIN, 0) is False

    def test_director_cache_fresh_nonexistent(self, cache):
        assert cache.is_director_cache_fresh("FAKE_CIN", 90) is False


class TestDonorOperations:
    """Tests for donor record management."""

    def test_get_donors(self, populated_cache):
        donors = populated_cache.get_donors()
        assert len(donors) == 2

    def test_get_donors_with_min_year(self, populated_cache):
        donors = populated_cache.get_donors(min_year=2025)
        assert len(donors) == 1
        assert donors[0]["donor_name"] == "Donor Infrastructure Pvt Ltd"

    def test_get_donors_with_min_amount(self, populated_cache):
        donors = populated_cache.get_donors(min_amount=10_000_000)
        assert len(donors) == 1
        assert donors[0]["amount"] == 50_000_000

    def test_get_donors_by_cin(self, populated_cache):
        donors = populated_cache.get_donors_by_cin(DONOR_CIN)
        assert len(donors) == 1

    def test_upsert_donor_updates_existing(self, populated_cache):
        """Same donor+trust+year should update, not duplicate."""
        populated_cache.upsert_donor(
            donor_name="Donor Infrastructure Pvt Ltd",
            amount=75_000_000,
            year=2025,
            trust_name="Prudent Electoral Trust",
            source="electoral_trust",
        )
        donors = populated_cache.get_donors()
        matching = [d for d in donors if d["donor_name"] == "Donor Infrastructure Pvt Ltd"]
        assert len(matching) == 1
        assert matching[0]["amount"] == 75_000_000


class TestAnnouncementOperations:
    """Tests for announcement caching and querying."""

    def test_insert_and_count_contracts(self, populated_cache):
        count = populated_cache.get_contract_announcement_count("540001")
        assert count == 3

    def test_no_duplicate_announcements(self, populated_cache):
        """Inserting the same announcement twice should be a no-op."""
        populated_cache.insert_announcement(
            scrip_code="540001",
            title="Award of Order worth ₹450 Cr from Indian Railways",
            date="2026-07-10",
            is_contract=True,
        )
        count = populated_cache.get_contract_announcement_count("540001")
        assert count == 3  # Still 3, not 4

    def test_get_unprocessed_contracts(self, populated_cache):
        unprocessed = populated_cache.get_unprocessed_contracts()
        assert len(unprocessed) >= 4  # 3 RAILCO + 1 DEFCO contracts

    def test_mark_processed(self, populated_cache):
        unprocessed = populated_cache.get_unprocessed_contracts()
        first_id = unprocessed[0]["id"]
        populated_cache.mark_announcement_processed(first_id)
        remaining = populated_cache.get_unprocessed_contracts()
        assert len(remaining) == len(unprocessed) - 1


class TestHeldPositions:
    """Tests for held position lifecycle."""

    def test_add_and_get_held_position(self, cache):
        cache.add_held_position("540001", "Test Co", alpha_score=0.72)
        held = cache.get_held_positions()
        assert len(held) == 1
        assert held[0]["scrip_code"] == "540001"
        assert held[0]["alpha_score"] == 0.72

    def test_remove_held_position(self, cache):
        cache.add_held_position("540001", "Test Co")
        cache.remove_held_position("540001")
        assert len(cache.get_held_positions()) == 0

    def test_expired_positions_not_returned(self, cache):
        cache.add_held_position("540001", "Test Co", expiry_days=0)
        held = cache.get_held_positions()
        assert len(held) == 0

    def test_cleanup_expired(self, cache):
        cache.add_held_position("540001", "Test Co", expiry_days=0)
        removed = cache.cleanup_expired_positions()
        assert removed == 1

    def test_upsert_updates_existing_position(self, cache):
        cache.add_held_position("540001", "Test Co", alpha_score=0.5)
        cache.add_held_position("540001", "Test Co", alpha_score=0.8)
        held = cache.get_held_positions()
        assert len(held) == 1
        assert held[0]["alpha_score"] == 0.8


class TestSystemLog:
    """Tests for pipeline health logging."""

    def test_log_event(self, cache):
        cache.log_event("test_module", "test_event", "details here")
        # No assertion on read (no public getter), just verify no crash

    def test_get_table_counts(self, populated_cache):
        counts = populated_cache.get_table_counts()
        assert counts["companies"] == 3
        assert counts["watchlist"] == 2
        assert counts["directors"] == 4  # 2 on RAILCO + 1 on DEFCO + 1 on DONORCO (composite PK: din+cin)
        assert counts["donors"] == 2
        assert counts["announcements"] == 5
