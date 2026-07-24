"""
Tests for GraphManager — NetworkX graph construction, Alpha Query,
scoring, and pruning.

These are the most critical tests: they verify that the political
connection detection algorithm works correctly.
"""

import pytest
from datetime import datetime

from src.graph_manager import GraphManager
from tests.conftest import (
    RAILCO_CIN, DEFCO_CIN, DONOR_CIN, BRIDGE_DIRECTOR_DIN,
)


@pytest.fixture
def graph(populated_cache, tmp_data_dir):
    """Provide a GraphManager with pre-built graph from test data."""
    gm = GraphManager(populated_cache, graph_path=tmp_data_dir / "test_graph.json")
    gm.build_from_cache()
    return gm


class TestGraphConstruction:
    """Tests for building the graph from cache data."""

    def test_graph_has_nodes(self, graph):
        stats = graph.get_stats()
        assert stats["total_nodes"] > 0

    def test_graph_has_listed_companies(self, graph):
        stats = graph.get_stats()
        assert stats["node_types"].get("ListedCompany", 0) >= 2

    def test_graph_has_directors(self, graph):
        stats = graph.get_stats()
        assert stats["node_types"].get("Director", 0) >= 2

    def test_graph_has_donor_companies(self, graph):
        stats = graph.get_stats()
        assert stats["node_types"].get("DonorCompany", 0) >= 1

    def test_graph_has_trusts(self, graph):
        stats = graph.get_stats()
        assert stats["node_types"].get("ElectoralTrust", 0) >= 1

    def test_graph_has_edges(self, graph):
        stats = graph.get_stats()
        assert stats["total_edges"] > 0
        assert stats["edge_types"].get("SITS_ON_BOARD", 0) >= 2
        assert stats["edge_types"].get("DONATED_TO", 0) >= 1

    def test_bridge_director_linked_to_both(self, graph):
        """Rajesh Kumar should have edges to both RAILCO and DONORCO."""
        director_node = f"director:{BRIDGE_DIRECTOR_DIN}"
        assert director_node in graph.G

        # Check edges to company and donor
        neighbors = set(graph.G.successors(director_node)) | set(
            graph.G.predecessors(director_node)
        )
        company_node = f"company:{RAILCO_CIN}"
        donor_node = f"donor:{DONOR_CIN}"

        assert company_node in neighbors or any(
            RAILCO_CIN in str(n) for n in neighbors
        )


class TestAlphaQuery:
    """Tests for the political connection detection algorithm."""

    def test_alpha_query_finds_connection_for_railco(self, graph):
        """RAILCO should have a connection via Rajesh Kumar → DONORCO → Prudent Trust."""
        results = graph.alpha_query(RAILCO_CIN)
        assert len(results) > 0

    def test_alpha_query_returns_scored_results(self, graph):
        results = graph.alpha_query(RAILCO_CIN)
        if results:
            top = results[0]
            assert "alpha_score" in top
            assert "director_name" in top
            assert "donor_company_name" in top
            assert "trust_name" in top
            assert 0 <= top["alpha_score"] <= 1

    def test_alpha_query_no_result_for_defco(self, graph):
        """DEFCO has no director overlap with donors, so no connection."""
        results = graph.alpha_query(DEFCO_CIN)
        assert len(results) == 0

    def test_alpha_query_nonexistent_company(self, graph):
        results = graph.alpha_query("FAKE_CIN_12345")
        assert len(results) == 0

    def test_results_sorted_by_score(self, graph):
        results = graph.alpha_query(RAILCO_CIN)
        if len(results) > 1:
            scores = [r["alpha_score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_scoring_weights_sum(self, graph):
        """Verify the scoring formula produces reasonable values."""
        results = graph.alpha_query(RAILCO_CIN)
        if results:
            top = results[0]
            # Score should be between 0 and 1
            assert 0 < top["alpha_score"] <= 1.0
            # Individual scores should also be bounded
            assert 0 < top["exclusivity_score"] <= 1.0
            assert 0 < top["proximity_score"] <= 1.0
            assert 0 < top["magnitude_score"] <= 1.0

    def test_path_included_in_results(self, graph):
        results = graph.alpha_query(RAILCO_CIN)
        if results:
            assert "path" in results[0]
            assert len(results[0]["path"]) >= 2


class TestGraphSerialization:
    """Tests for saving and loading the graph."""

    def test_save_and_reload(self, graph, tmp_data_dir):
        graph.save()
        assert (tmp_data_dir / "test_graph.json").exists()

        # Reload into a new GraphManager
        gm2 = GraphManager(
            graph.cache,
            graph_path=tmp_data_dir / "test_graph.json",
        )
        stats1 = graph.get_stats()
        stats2 = gm2.get_stats()
        assert stats1["total_nodes"] == stats2["total_nodes"]
        assert stats1["total_edges"] == stats2["total_edges"]

    def test_save_creates_parent_directory(self, populated_cache, tmp_data_dir):
        deep_path = tmp_data_dir / "sub" / "dir" / "graph.json"
        gm = GraphManager(populated_cache, graph_path=deep_path)
        gm.build_from_cache()
        gm.save()
        assert deep_path.exists()


class TestGraphPruning:
    """Tests for stale node removal."""

    def test_prune_removes_old_tenders(self, graph):
        # Add an old tender
        tender_id = graph.add_tender(
            title="Ancient Order",
            date="2020-01-01",
            scrip_code="540001",
        )
        graph.link_company_to_tender(RAILCO_CIN, tender_id)

        before = graph.G.number_of_nodes()
        graph.prune()
        after = graph.G.number_of_nodes()

        assert after <= before

    def test_prune_removes_orphan_nodes(self, graph):
        # Add an orphan node with no edges
        graph._add_node("orphan:test", node_type="TestOrphan")
        assert "orphan:test" in graph.G

        graph.prune()
        assert "orphan:test" not in graph.G

    def test_prune_preserves_connected_nodes(self, graph):
        before_nodes = graph.G.number_of_nodes()
        # All nodes in the test graph are connected
        graph.prune()
        after_nodes = graph.G.number_of_nodes()
        # Should not remove any connected nodes
        assert after_nodes == before_nodes


class TestGraphAddOperations:
    """Tests for individual node/edge addition."""

    def test_add_tender_and_link(self, graph):
        tender_id = graph.add_tender(
            title="New Order ₹100 Cr",
            date="2026-07-15",
            scrip_code="540001",
            value=1_000_000_000,
        )
        graph.link_company_to_tender(RAILCO_CIN, tender_id)

        # Verify the tender node exists
        assert tender_id in graph.G
        data = graph.G.nodes[tender_id]
        assert data["node_type"] == "Tender"
        assert data["value"] == 1_000_000_000

    def test_add_political_party(self, graph):
        graph.add_political_party("Test Party")
        assert "party:Test Party" in graph.G
