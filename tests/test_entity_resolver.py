"""
Tests for EntityResolver — CIN/DIN-based entity matching.

Covers: name normalization, CIN resolution, donor resolution,
fuzzy matching tiers, and director overlap detection.
"""

import pytest

from src.entity_resolver import EntityResolver
from tests.conftest import (
    RAILCO_CIN, DEFCO_CIN, DONOR_CIN, BRIDGE_DIRECTOR_DIN,
)


class TestNameNormalization:
    """Tests for company name normalization."""

    def test_strips_common_suffixes(self):
        assert EntityResolver.normalize_company_name(
            "ABC Infra Projects Ltd."
        ) == "abc infra projects"

    def test_strips_pvt_limited(self):
        result = EntityResolver.normalize_company_name(
            "XYZ Private Limited"
        )
        assert "private" not in result
        assert "limited" not in result

    def test_removes_punctuation(self):
        result = EntityResolver.normalize_company_name(
            "A.B.C. Infrastructure (India)"
        )
        assert "." not in result
        assert "(" not in result
        assert ")" not in result

    def test_collapses_whitespace(self):
        result = EntityResolver.normalize_company_name(
            "  Too   Many   Spaces  "
        )
        assert "  " not in result
        assert result == result.strip()

    def test_empty_string(self):
        assert EntityResolver.normalize_company_name("") == ""

    def test_none_handling(self):
        assert EntityResolver.normalize_company_name(None) == ""


class TestCompanyCINResolution:
    """Tests for resolving company names to CINs."""

    def test_resolve_by_scrip_code(self, populated_cache):
        resolver = EntityResolver(populated_cache)
        cin = resolver.resolve_company_cin(
            "Rail Electrification Co Ltd", scrip_code="540001"
        )
        assert cin == RAILCO_CIN

    def test_resolve_by_exact_name(self, populated_cache):
        resolver = EntityResolver(populated_cache)
        cin = resolver.resolve_company_cin("Rail Electrification Co Ltd")
        assert cin == RAILCO_CIN

    def test_resolve_nonexistent(self, populated_cache):
        resolver = EntityResolver(populated_cache)
        cin = resolver.resolve_company_cin("Completely Fake Company XYZ")
        assert cin is None


class TestDonorCINResolution:
    """Tests for resolving Electoral Trust donors to CINs."""

    def test_resolve_known_donor(self, populated_cache):
        """Donor with CIN already stored should resolve."""
        resolver = EntityResolver(populated_cache)
        # The donor "Donor Infrastructure Pvt Ltd" has CIN in the donors table
        # but resolve_donor_cin looks it up in the companies table
        # We need to also add it as a company for resolution to work
        populated_cache.upsert_company(
            scrip_code="999001",
            name="Donor Infrastructure Pvt Ltd",
            cin=DONOR_CIN,
        )
        resolver.invalidate_caches()
        cin = resolver.resolve_donor_cin("Donor Infrastructure Pvt Ltd")
        assert cin == DONOR_CIN

    def test_resolve_all_donors_counts(self, populated_cache):
        resolver = EntityResolver(populated_cache)
        result = resolver.resolve_all_donors()
        assert "resolved" in result
        assert "unresolved" in result
        assert "total" in result
        assert result["total"] == 2


class TestDirectorOverlap:
    """Tests for detecting director-donor board overlaps."""

    def test_find_bridge_director(self, populated_cache):
        """Rajesh Kumar (00000001) sits on RAILCO and DONORCO boards."""
        resolver = EntityResolver(populated_cache)
        overlaps = resolver.find_director_overlap(RAILCO_CIN)

        # Should find Rajesh Kumar as the bridge
        bridge_dins = [o["din"] for o in overlaps]
        assert BRIDGE_DIRECTOR_DIN in bridge_dins

    def test_no_overlap_for_isolated_company(self, populated_cache):
        """DEFCO has no directors on donor boards."""
        resolver = EntityResolver(populated_cache)
        overlaps = resolver.find_director_overlap(DEFCO_CIN)
        assert len(overlaps) == 0

    def test_overlap_includes_donation_data(self, populated_cache):
        resolver = EntityResolver(populated_cache)
        overlaps = resolver.find_director_overlap(RAILCO_CIN)

        if overlaps:
            overlap = overlaps[0]
            assert "donations" in overlap
            assert "director_name" in overlap
            assert "donor_company_name" in overlap
            assert overlap["total_board_seats"] >= 2

    def test_cache_invalidation(self, populated_cache):
        resolver = EntityResolver(populated_cache)
        resolver.invalidate_caches()
        assert resolver._company_name_index is None
        assert resolver._donor_name_index is None
