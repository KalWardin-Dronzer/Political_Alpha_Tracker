"""
Political Alpha Tracker — Graph Manager (NetworkX)

Maintains an in-memory political connection graph using NetworkX.
Serialized to JSON file for persistence across runs.

Graph Model:
    Nodes: ListedCompany, Director, DonorCompany, ElectoralTrust, PoliticalParty, Tender
    Edges: SITS_ON_BOARD, DONATED_TO, FUNDED, WON_CONTRACT

The Alpha Query:
    Finds paths from a ListedCompany to an ElectoralTrust through shared directors,
    scores them by director exclusivity, path proximity, and donation magnitude.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import networkx as nx
from thefuzz import fuzz, process

from src.config import (
    GRAPH_FILE, DATA_DIR,
    ALPHA_WEIGHT_EXCLUSIVITY, ALPHA_WEIGHT_PROXIMITY,
    ALPHA_WEIGHT_MAGNITUDE, ALPHA_SCORE_THRESHOLD,
    MAX_PATH_HOPS, DONATION_RECENCY_YEARS, DONATION_MIN_AMOUNT,
    TENDER_MAX_AGE_MONTHS,
)
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class GraphManager:
    """
    Manages the political connection graph.

    Usage:
        gm = GraphManager(cache)
        gm.build_from_cache()
        results = gm.alpha_query("L12345MH2000PLC123456")
        gm.save()
    """

    def __init__(self, cache: CacheManager, graph_path: Path = None):
        self.cache = cache
        self.graph_path = graph_path or GRAPH_FILE
        self.G = nx.DiGraph()

        # Load existing graph if available
        if self.graph_path.exists():
            self._load()

    def _load(self):
        """Load graph from JSON file."""
        try:
            with open(self.graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.G = nx.node_link_graph(data, directed=True)
            logger.info(
                f"Loaded graph: {self.G.number_of_nodes()} nodes, "
                f"{self.G.number_of_edges()} edges"
            )
        except Exception as e:
            logger.warning(f"Could not load graph from {self.graph_path}: {e}")
            self.G = nx.DiGraph()

    def save(self):
        """Serialize graph to JSON file."""
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        data = nx.node_link_data(self.G)
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(
            f"Saved graph: {self.G.number_of_nodes()} nodes, "
            f"{self.G.number_of_edges()} edges"
        )

    # ──────────────────────────────────────────
    # Graph Construction
    # ──────────────────────────────────────────
    def _add_node(self, node_id: str, node_type: str, **attrs):
        """Add or update a node with type label and attributes."""
        self.G.add_node(node_id, node_type=node_type, **attrs)

    def _add_edge(self, source: str, target: str, edge_type: str, **attrs):
        """Add or update an edge with type label and attributes."""
        self.G.add_edge(source, target, edge_type=edge_type, **attrs)

    def add_listed_company(self, cin: str, name: str,
                            scrip_code: str = "", sector: str = "",
                            market_cap: float = 0):
        """Add a ListedCompany node."""
        self._add_node(
            f"company:{cin}",
            node_type="ListedCompany",
            cin=cin, name=name, scrip_code=scrip_code,
            sector=sector, market_cap=market_cap,
        )

    def add_director(self, din: str, name: str, is_bureaucrat: int = 0):
        """Add a Director node."""
        self._add_node(
            f"director:{din}",
            node_type="Director",
            din=din, name=name, is_bureaucrat=is_bureaucrat
        )

    def add_donor_company(self, cin: str, name: str):
        """Add a DonorCompany node (Electoral Trust/Bond donor)."""
        self._add_node(
            f"donor:{cin}",
            node_type="DonorCompany",
            cin=cin, name=name,
        )

    def add_electoral_trust(self, name: str):
        """Add an ElectoralTrust node."""
        self._add_node(
            f"trust:{name}",
            node_type="ElectoralTrust",
            name=name,
        )

    def add_political_party(self, name: str):
        """Add a PoliticalParty node."""
        self._add_node(
            f"party:{name}",
            node_type="PoliticalParty",
            name=name,
        )

    def add_tender(self, title: str, date: str,
                    scrip_code: str = "", value: float = 0):
        """Add a Tender node."""
        tender_id = f"tender:{scrip_code}:{date}:{hash(title) % 100000}"
        self._add_node(
            tender_id,
            node_type="Tender",
            title=title, date=date,
            scrip_code=scrip_code, value=value,
        )
        return tender_id

    def link_director_to_company(self, din: str, cin: str):
        """Director SITS_ON_BOARD of Company."""
        self._add_edge(
            f"director:{din}", f"company:{cin}",
            edge_type="SITS_ON_BOARD",
        )

    def link_director_to_donor(self, din: str, donor_cin: str):
        """Director SITS_ON_BOARD of DonorCompany."""
        self._add_edge(
            f"director:{din}", f"donor:{donor_cin}",
            edge_type="SITS_ON_BOARD",
        )

    def link_donor_to_trust(self, donor_cin: str, trust_name: str,
                             amount: float, year: int):
        """DonorCompany DONATED_TO ElectoralTrust."""
        self._add_edge(
            f"donor:{donor_cin}", f"trust:{trust_name}",
            edge_type="DONATED_TO",
            amount=amount, year=year,
        )

    def link_trust_to_party(self, trust_name: str, party_name: str,
                             amount: float = 0, year: int = 0):
        """ElectoralTrust FUNDED PoliticalParty."""
        self._add_edge(
            f"trust:{trust_name}", f"party:{party_name}",
            edge_type="FUNDED",
            amount=amount, year=year,
        )

    def link_company_to_tender(self, cin: str, tender_id: str):
        """ListedCompany WON_CONTRACT Tender."""
        self._add_edge(
            f"company:{cin}", tender_id,
            edge_type="WON_CONTRACT",
        )

    # ──────────────────────────────────────────
    # Build Graph from Cache
    # ──────────────────────────────────────────
    def build_from_cache(self):
        """
        Reconstruct the full graph from SQLite cache data.
        Called during quarterly refresh or initial setup.
        """
        logger.info("Building graph from cache...")

        # 1. Add all watchlist companies
        watchlist = self.cache.get_watchlist()
        for company in watchlist:
            cin = company.get("cin")
            if cin:
                self.add_listed_company(
                    cin=cin,
                    name=company["name"],
                    scrip_code=company["scrip_code"],
                    sector=company.get("sector", ""),
                    market_cap=company.get("market_cap", 0),
                )

                # Add directors for this company
                directors = self.cache.get_directors_for_company(cin)
                for d in directors:
                    self.add_director(d["din"], d["name"], is_bureaucrat=d.get("is_bureaucrat", 0))
                    self.link_director_to_company(d["din"], cin)

        # 2. Add all donors
        donors = self.cache.get_donors()
        seen_trusts = set()
        seen_parties = set()

        for donor in donors:
            donor_cin = donor.get("donor_cin")
            if not donor_cin:
                continue

            # Add donor company
            self.add_donor_company(donor_cin, donor["donor_name"])

            # Add trust node if applicable
            trust_name = donor.get("trust_name")
            if trust_name:
                if trust_name not in seen_trusts:
                    self.add_electoral_trust(trust_name)
                    seen_trusts.add(trust_name)

                self.link_donor_to_trust(
                    donor_cin, trust_name,
                    amount=donor["amount"],
                    year=donor["year"],
                )

            # Add party node if applicable
            party_name = donor.get("recipient_party")
            if party_name:
                if party_name not in seen_parties:
                    self.add_political_party(party_name)
                    seen_parties.add(party_name)

                if trust_name:
                    self.link_trust_to_party(
                        trust_name, party_name,
                        amount=donor["amount"],
                        year=donor["year"],
                    )

        # 3. Link directors to donor companies
        # For each director in the graph, check if they also sit on
        # any donor company boards
        for node, data in list(self.G.nodes(data=True)):
            if data.get("node_type") == "Director":
                din = data.get("din", "")
                all_boards = self.cache.get_all_companies_for_director(din)
                for board in all_boards:
                    board_cin = board.get("cin")
                    if board_cin and f"donor:{board_cin}" in self.G:
                        self.link_director_to_donor(din, board_cin)

        # 4. Direct ListedCompany to Trust/Party matching (Fuzzy Match)
        donors_list = list(donors) # iterate over donors again
        donor_names = list(set(d["donor_name"] for d in donors_list if d.get("donor_name")))
        
        # Get all listed companies in the database
        company_names = []
        company_map = {}
        all_companies = self.cache.get_all_companies()
        for company in all_companies:
            name_upper = company.get("name", "").upper()
            if name_upper:
                company_names.append(name_upper)
                # Map name to the full company dict so we can add it to graph if matched
                company_map[name_upper] = company
        
        matched_donor_to_company = {}
        for d_name in donor_names:
            result = process.extractOne(d_name.upper(), company_names, scorer=fuzz.token_set_ratio)
            if result and result[1] >= 88:
                matched_donor_to_company[d_name] = company_map[result[0]]
                logger.info(f"Direct donor match: {d_name} -> {result[0]} (score: {result[1]}%)")

        for donor in donors_list:
            d_name = donor.get("donor_name")
            if d_name in matched_donor_to_company:
                company = matched_donor_to_company[d_name]
                cin = company.get("cin")
                if not cin: continue
                
                company_node = f"company:{cin}"
                if company_node not in self.G:
                    self.add_listed_company(
                        cin=cin,
                        name=company["name"],
                        scrip_code=company["scrip_code"],
                        sector=company.get("sector", ""),
                        market_cap=company.get("market_cap", 0),
                    )
                    
                    # Add directors for this company as well so the graph is complete
                    directors = self.cache.get_directors_for_company(cin)
                    for d in directors:
                        self.add_director(d["din"], d["name"], is_bureaucrat=d.get("is_bureaucrat", 0))
                        self.link_director_to_company(d["din"], cin)

                trust_name = donor.get("trust_name")
                if trust_name:
                    if trust_name not in seen_trusts:
                        self.add_electoral_trust(trust_name)
                        seen_trusts.add(trust_name)
                    # Add edge ListedCompany -> DONATED_TO -> Trust
                    self.G.add_edge(
                        company_node, f"trust:{trust_name}",
                        edge_type="DONATED_TO",
                        amount=donor["amount"],
                        year=donor["year"],
                    )

        logger.info(
            f"Graph built: {self.G.number_of_nodes()} nodes, "
            f"{self.G.number_of_edges()} edges"
        )

        self.cache.log_event(
            "graph_manager", "graph_built",
            f"Nodes: {self.G.number_of_nodes()}, "
            f"Edges: {self.G.number_of_edges()}"
        )

    # ──────────────────────────────────────────
    # The Alpha Query
    # ──────────────────────────────────────────
    def alpha_query(self, target_cin: str) -> list[dict]:
        """
        The core political connection detection query.

        Finds paths from a ListedCompany to an ElectoralTrust through
        shared directors and donor companies. Scores each connection by:
            - Director exclusivity (fewer board seats = higher signal)
            - Path proximity (fewer hops = stronger)
            - Donation magnitude (larger = more significant)

        Args:
            target_cin: CIN of the company to investigate.

        Returns:
            List of scored connection dicts, sorted by alpha_score descending.
        """
        company_node = f"company:{target_cin}"
        if company_node not in self.G:
            logger.debug(f"Company {target_cin} not in graph")
            return []

        results = []
        current_year = datetime.now().year

        # Find all trust/party nodes
        trust_nodes = [
            n for n, d in self.G.nodes(data=True)
            if d.get("node_type") in ("ElectoralTrust", "PoliticalParty")
        ]

        # For path finding, we need an undirected view
        G_undirected = self.G.to_undirected()

        for trust_node in trust_nodes:
            try:
                # Find all simple paths up to MAX_PATH_HOPS
                paths = list(nx.all_simple_paths(
                    G_undirected, company_node, trust_node,
                    cutoff=MAX_PATH_HOPS,
                ))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

            for path in paths:
                # Analyze the path
                connection = self._analyze_path(path, current_year)
                if connection:
                    results.append(connection)

        # Deduplicate by bridging director
        seen = set()
        unique_results = []
        for r in results:
            key = (r["director_din"], r.get("donor_cin", ""))
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        # Sort by alpha score
        unique_results.sort(key=lambda x: x["alpha_score"], reverse=True)

        return unique_results

    def _analyze_path(self, path: list[str],
                       current_year: int) -> Optional[dict]:
        """
        Analyze a single graph path and compute the alpha score.

        Returns:
            Scored connection dict, or None if filters disqualify it.
        """
        # Extract node types along the path
        path_nodes = [
            (node, self.G.nodes[node]) for node in path
        ]

        # Find the bridging director
        director_node = None
        for node, data in path_nodes:
            if data.get("node_type") == "Director":
                director_node = (node, data)
                break

        # Find the donor company
        donor_node = None
        for node, data in path_nodes:
            if data.get("node_type") == "DonorCompany":
                donor_node = (node, data)
                break

        is_direct = False
        if not director_node and not donor_node:
            # Check for direct path: ListedCompany -> DONATED_TO -> Trust/Party
            if len(path) >= 2 and path_nodes[0][1].get("node_type") == "ListedCompany":
                is_direct = True
                donor_id = path[0]
            else:
                return None
        else:
            if not director_node or not donor_node:
                return None
            donor_id = donor_node[0]

        # Find the trust/party
        trust_node = None
        for node, data in path_nodes:
            if data.get("node_type") in ("ElectoralTrust", "PoliticalParty"):
                trust_node = (node, data)
                break

        # Get donation details from edges
        donations = []
        for _, target, edge_data in self.G.out_edges(donor_id, data=True):
            if edge_data.get("edge_type") == "DONATED_TO":
                donations.append(edge_data)

        if not donations:
            return None

        # Apply filters
        # Filter 1: Donation recency
        recent_donations = [
            d for d in donations
            if d.get("year", 0) >= current_year - DONATION_RECENCY_YEARS
        ]
        if not recent_donations:
            return None

        # Filter 2: Donation magnitude
        max_donation = max(d.get("amount", 0) for d in recent_donations)
        if max_donation < DONATION_MIN_AMOUNT:
            return None

        # Compute scores
        if is_direct:
            exclusivity_score = 2.0  # Direct donation is strongest
            din = ""
            total_board_seats = 0
        else:
            # Score 1: Director exclusivity
            din = director_node[1].get("din", "")
            total_board_seats = sum(
                1 for _ in self.G.successors(director_node[0])
            )
            # Also count predecessors (undirected board connections)
            total_board_seats += sum(
                1 for _ in self.G.predecessors(director_node[0])
            )
            total_board_seats = max(total_board_seats, 1)
            exclusivity_score = 1.0 / total_board_seats

        # Score 2: Path proximity
        path_length = len(path) - 1  # Edges = nodes - 1
        proximity_score = 1.0 / max(path_length, 1)

        # Score 3: Donation magnitude (tiered)
        if max_donation >= 1e8:  # > ₹10 Crore
            magnitude_score = 1.0
        elif max_donation >= 1e7:  # > ₹1 Crore
            magnitude_score = 0.7
        elif max_donation >= DONATION_MIN_AMOUNT:  # > ₹10 Lakh
            magnitude_score = 0.4
        else:
            magnitude_score = 0.1

        party_name = ""
        if trust_node:
            if trust_node[1].get("node_type") == "PoliticalParty":
                party_name = trust_node[1].get("name", "")
            else: # ElectoralTrust
                # Find successor party
                for _, target in self.G.out_edges(trust_node[0]):
                    if self.G.nodes[target].get("node_type") == "PoliticalParty":
                        party_name = self.G.nodes[target].get("name", "")
                        break
                        
        # Phase 5: Election Cycle Weighting
        election_multiplier = 1.0
        if party_name:
            from src.config import STATE_PARTY_MAPPING, UPCOMING_ELECTIONS, ELECTION_MULTIPLIER
            from datetime import datetime
            party_lower = party_name.lower()
            current_date = datetime.now()
            
            # Find the state(s) this party operates in
            matched_states = []
            for state, parties in STATE_PARTY_MAPPING.items():
                if any(p in party_lower for p in parties):
                    matched_states.append(state)
                    
            for state in matched_states:
                if state in UPCOMING_ELECTIONS:
                    e_year, e_month = UPCOMING_ELECTIONS[state]
                    e_date = datetime(e_year, e_month, 1)
                    # If election is within 12 months (future) or just happened (past 1-2 months)
                    months_diff = (e_date.year - current_date.year) * 12 + (e_date.month - current_date.month)
                    if -2 <= months_diff <= 12:
                        election_multiplier = ELECTION_MULTIPLIER
                        break

        # Phase 5: Deep State Bureaucrat Weighting
        bureaucrat_multiplier = 1.0
        is_bureaucrat = False
        if not is_direct and director_node[1].get("is_bureaucrat"):
            bureaucrat_multiplier = 1.5
            is_bureaucrat = True

        # Weighted alpha score
        alpha_score = (
            ALPHA_WEIGHT_EXCLUSIVITY * exclusivity_score
            + ALPHA_WEIGHT_PROXIMITY * proximity_score
            + ALPHA_WEIGHT_MAGNITUDE * magnitude_score
        ) * election_multiplier * bureaucrat_multiplier

        # Get company details from the path
        company_node = path_nodes[0]
        return {
            "company_name": company_node[1].get("name", "Unknown"),
            "company_cin": company_node[1].get("cin", ""),
            "scrip_code": company_node[1].get("scrip_code", ""),
            "director_name": director_node[1].get("name", "Unknown") if director_node else "DIRECT_DONOR",
            "director_din": din,
            "donor_company_name": donor_node[1].get("name", "Unknown") if donor_node else company_node[1].get("name", "Unknown"),
            "donor_cin": donor_node[1].get("cin", "") if donor_node else company_node[1].get("cin", ""),
            "trust_name": trust_node[1].get("name", "") if trust_node else "",
            "party_name": party_name,
            "max_donation": max_donation,
            "donation_year": max(
                d.get("year", 0) for d in recent_donations
            ),
            "total_board_seats": total_board_seats,
            "path_length": path_length,
            "exclusivity_score": round(exclusivity_score, 3),
            "proximity_score": round(proximity_score, 3),
            "magnitude_score": round(magnitude_score, 3),
            "election_multiplier": election_multiplier,
            "bureaucrat_multiplier": bureaucrat_multiplier,
            "is_bureaucrat": is_bureaucrat,
            "is_direct_donor": is_direct,
            "alpha_score": round(alpha_score, 3),
            "path": [
                f"{self.G.nodes[n].get('node_type', '?')}:"
                f"{self.G.nodes[n].get('name', n)}"
                for n in path
            ],
        }

    # ──────────────────────────────────────────
    # Pruning
    # ──────────────────────────────────────────
    def prune(self):
        """
        Remove stale nodes and edges to keep the graph lean.

        Removes:
            - Tenders older than TENDER_MAX_AGE_MONTHS
            - Orphan nodes with no connections
        """
        before_nodes = self.G.number_of_nodes()
        before_edges = self.G.number_of_edges()

        # Remove old tenders
        cutoff = datetime.now() - timedelta(
            days=TENDER_MAX_AGE_MONTHS * 30
        )
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        tender_nodes_to_remove = []
        for node, data in self.G.nodes(data=True):
            if data.get("node_type") == "Tender":
                tender_date = data.get("date", "")
                if tender_date and tender_date < cutoff_str:
                    tender_nodes_to_remove.append(node)

        for node in tender_nodes_to_remove:
            self.G.remove_node(node)

        # Remove orphan nodes (no edges)
        orphans = [
            node for node in self.G.nodes()
            if self.G.degree(node) == 0
        ]
        for node in orphans:
            self.G.remove_node(node)

        after_nodes = self.G.number_of_nodes()
        after_edges = self.G.number_of_edges()

        logger.info(
            f"Pruned graph: {before_nodes} -> {after_nodes} nodes, "
            f"{before_edges} -> {after_edges} edges "
            f"(removed {len(tender_nodes_to_remove)} old tenders, "
            f"{len(orphans)} orphans)"
        )

        self.cache.log_event(
            "graph_manager", "pruned",
            f"Removed {before_nodes - after_nodes} nodes, "
            f"{before_edges - after_edges} edges"
        )

    # ──────────────────────────────────────────
    # Monitoring
    # ──────────────────────────────────────────
    def get_stats(self) -> dict:
        """Get graph statistics for monitoring."""
        node_types = {}
        for _, data in self.G.nodes(data=True):
            nt = data.get("node_type", "Unknown")
            node_types[nt] = node_types.get(nt, 0) + 1

        edge_types = {}
        for _, _, data in self.G.edges(data=True):
            et = data.get("edge_type", "Unknown")
            edge_types[et] = edge_types.get(et, 0) + 1

        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_types": node_types,
            "edge_types": edge_types,
        }
