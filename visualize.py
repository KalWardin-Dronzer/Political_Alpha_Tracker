import json
import networkx as nx
from pyvis.network import Network
import webbrowser
import os
import pathlib

from src.graph_manager import GraphManager
from src.cache_manager import CacheManager

def visualize_graph():
    graph_path = "data/graph.json"
    if not os.path.exists(graph_path):
        print(f"Error: {graph_path} not found.")
        return

    # Load the graph
    with open(graph_path, 'r') as f:
        data = json.load(f)
    
    G = nx.node_link_graph(data)

    # Initialize GraphManager to get alpha scores
    cache = CacheManager(pathlib.Path('data/cache.sqlite'))
    gm = GraphManager(cache, graph_path=pathlib.Path(graph_path))
    # Note: gm already loads the graph internally, we can use it to query

    # Initialize Pyvis network
    net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white", directed=False)
    net.force_atlas_2based()

    # Define colors and icons for different node types
    type_colors = {
        "ListedCompany": "#3498db",  # Blue
        "Director": "#f1c40f",       # Yellow
        "DonorCompany": "#e74c3c",   # Red
        "ElectoralTrust": "#2ecc71", # Green
        "PoliticalParty": "#9b59b6", # Purple
        "Tender": "#ecf0f1",         # Silver/White
    }

    # Pre-compute alpha scores for ListedCompanies
    company_alphas = {}
    for node_id, node_data in G.nodes(data=True):
        if node_data.get("node_type") == "ListedCompany":
            cin = node_data.get("cin")
            if cin:
                results = gm.alpha_query(cin)
                if results:
                    best = results[0]
                    company_alphas[node_id] = {
                        "score": best["alpha_score"],
                        "details": f"Max Donation: Rs.{best['max_donation']} via {best['director_name']} to {best['donor_company_name']}"
                    }

    # Add nodes to pyvis
    for node_id, node_data in G.nodes(data=True):
        node_type = node_data.get("node_type", "Unknown")
        color = type_colors.get(node_type, "#95a5a6")
        
        # Build tooltip title
        title = f"Type: {node_type}<br>"
        for k, v in node_data.items():
            if k not in ["node_type", "id", "label"]:
                title += f"{k}: {v}<br>"
                
        label = node_data.get("name", node_id)
        if len(label) > 20:
            label = label[:17] + "..."

        # Highlight Alpha Scores
        size = 25 if node_type == "Director" else 35
        if node_type == "ListedCompany" and node_id in company_alphas:
            alpha_info = company_alphas[node_id]
            title += f"<br><b>🔥 Alpha Score: {alpha_info['score']}</b><br>"
            title += f"<i>{alpha_info['details']}</i>"
            label = f"⭐ [{alpha_info['score']}] {label}"
            color = "#e67e22"  # Highlight color (Orange) for companies with alpha
            size = 45 # Make them bigger

        net.add_node(
            node_id, 
            label=label, 
            title=title, 
            color=color,
            size=size
        )

    # Add edges to pyvis
    for source, target, edge_data in G.edges(data=True):
        edge_type = edge_data.get("edge_type", "")
        title = f"Relation: {edge_type}<br>"
        for k, v in edge_data.items():
            if k not in ["edge_type"]:
                title += f"{k}: {v}<br>"
                
        net.add_edge(source, target, title=title, label=edge_type)

    # Generate and open HTML
    output_file = "graph_visualization.html"
    net.save_graph(output_file)
    print(f"Graph generated at {output_file}. Opening in browser...")
    webbrowser.open(f"file://{os.path.abspath(output_file)}")

if __name__ == "__main__":
    visualize_graph()
