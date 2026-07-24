"""
Integration test — end-to-end pipeline simulation.

Simulates the daily pipeline flow without network calls:
    1. Populated cache (as if quarterly refresh already ran)
    2. Simulate a new contract announcement
    3. Build graph
    4. Run Alpha Query
    5. Verify the alert would fire with correct scoring
"""

import pytest

from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from src.entity_resolver import EntityResolver
from src.config import ALPHA_SCORE_THRESHOLD
from tests.conftest import RAILCO_CIN, DEFCO_CIN, DONOR_CIN, BRIDGE_DIRECTOR_DIN


class TestEndToEndPipeline:
    """
    Simulates a full daily pipeline cycle with test data.
    No network calls — everything runs against the populated_cache fixture.
    """

    def test_full_alert_pipeline(self, populated_cache, tmp_data_dir):
        """
        Scenario: RAILCO wins a new government contract.
        Expected: Alpha Query finds connection via Rajesh Kumar → DONORCO → Prudent Trust.
        """
        cache = populated_cache

        # Step 1: Build graph from cache
        graph = GraphManager(cache, graph_path=tmp_data_dir / "e2e_graph.json")
        graph.build_from_cache()

        stats = graph.get_stats()
        assert stats["total_nodes"] > 0
        assert stats["total_edges"] > 0

        # Step 2: Simulate a new contract announcement arriving
        cache.insert_announcement(
            scrip_code="540001",
            title="Order received from NHSRCL for bullet train components worth ₹200 Cr",
            date="2026-07-15",
            category="Corporate",
            is_contract=True,
        )

        # Step 3: Look up the company
        company = cache.get_company("540001")
        assert company is not None
        assert company["cin"] == RAILCO_CIN

        # Step 4: Run Alpha Query
        connections = graph.alpha_query(RAILCO_CIN)

        # Step 5: Verify connection is found
        assert len(connections) > 0, (
            "Alpha Query should find at least one connection for RAILCO"
        )

        top = connections[0]
        assert top["alpha_score"] > 0
        assert top["director_din"] == BRIDGE_DIRECTOR_DIN
        assert "Rajesh Kumar" in top["director_name"]
        assert DONOR_CIN in top["donor_cin"]

        # Step 6: Add tender to graph
        tender_id = graph.add_tender(
            title="Order from NHSRCL ₹200 Cr",
            date="2026-07-15",
            scrip_code="540001",
            value=2_000_000_000,
        )
        graph.link_company_to_tender(RAILCO_CIN, tender_id)

        # Step 7: Add to held positions
        cache.add_held_position(
            scrip_code="540001",
            name="Rail Electrification Co Ltd",
            alpha_score=top["alpha_score"],
        )

        held = cache.get_held_positions()
        assert len(held) == 1
        assert held[0]["scrip_code"] == "540001"

        # Step 8: Save graph
        graph.save()
        assert (tmp_data_dir / "e2e_graph.json").exists()

    def test_no_alert_for_clean_company(self, populated_cache, tmp_data_dir):
        """
        Scenario: DEFCO wins a contract, but has no political connections.
        Expected: Alpha Query returns empty, no alert fired.
        """
        cache = populated_cache

        graph = GraphManager(cache, graph_path=tmp_data_dir / "e2e_graph2.json")
        graph.build_from_cache()

        # DEFCO contract
        cache.insert_announcement(
            scrip_code="540002",
            title="Contract for supply of defence radars worth ₹500 Cr",
            date="2026-07-15",
            is_contract=True,
        )

        # Alpha Query should return nothing for DEFCO
        connections = graph.alpha_query(DEFCO_CIN)
        assert len(connections) == 0

    def test_exit_command_removes_position(self, populated_cache):
        """
        Scenario: User sends /exit 540001 → position should be removed.
        """
        cache = populated_cache

        # Add position
        cache.add_held_position("540001", "RAILCO", alpha_score=0.7)
        assert len(cache.get_held_positions()) == 1

        # Simulate /exit command
        cache.remove_held_position("540001")
        assert len(cache.get_held_positions()) == 0

    def test_watchlist_plus_held_monitoring_set(self, populated_cache):
        """
        The monitoring set should include both watchlist AND held positions.
        """
        cache = populated_cache

        # RAILCO and DEFCO are on watchlist
        watchlist = cache.get_watchlist()
        assert len(watchlist) == 2

        # Add a non-watchlist company to held positions
        cache.add_held_position("540003", "Highway Builders")

        # Combined monitoring set
        watchlist_codes = {c["scrip_code"] for c in watchlist}
        held_codes = {h["scrip_code"] for h in cache.get_held_positions()}
        monitoring_set = watchlist_codes | held_codes

        assert "540001" in monitoring_set
        assert "540002" in monitoring_set
        assert "540003" in monitoring_set  # Held, not on watchlist

    def test_graph_rebuild_idempotent(self, populated_cache, tmp_data_dir):
        """Building graph twice from the same data should produce same result."""
        graph = GraphManager(
            populated_cache,
            graph_path=tmp_data_dir / "idempotent_graph.json",
        )

        graph.build_from_cache()
        stats1 = graph.get_stats()

        graph.build_from_cache()
        stats2 = graph.get_stats()

        assert stats1["total_nodes"] == stats2["total_nodes"]
        assert stats1["total_edges"] == stats2["total_edges"]

    def test_entity_resolver_with_graph(self, populated_cache, tmp_data_dir):
        """
        EntityResolver.find_director_overlap should identify the same
        connection that the Alpha Query finds.
        """
        resolver = EntityResolver(populated_cache)
        overlaps = resolver.find_director_overlap(RAILCO_CIN)

        # Should find Rajesh Kumar as bridge
        assert len(overlaps) > 0
        bridge = overlaps[0]
        assert bridge["din"] == BRIDGE_DIRECTOR_DIN
        assert bridge["donor_company_cin"] == DONOR_CIN
        assert len(bridge["donations"]) > 0
        assert bridge["donations"][0]["amount"] == 50_000_000
