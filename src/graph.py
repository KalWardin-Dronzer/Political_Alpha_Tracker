"""
The connection graph: listed companies that bought electoral bonds, linked to
one Electoral Bonds node and to their sector.

The SBI disclosure names purchasers but not the party that redeemed each bond,
so every purchase edge ends at the same node. Sector nodes give the picture its
structure; companies without a sector label link to the bonds node only.

    save_html(build_graph(), "results/connections.html")   interactive (pyvis)
    save_png(build_graph(), "results/figures/connections-dark.png", dark=True)
"""

import math
import re
from pathlib import Path

import networkx as nx

from src.connections import connections

BONDS = "Electoral Bonds"

# Validated categorical slots 1-3 (blue, orange, aqua) for light and dark surfaces.
THEMES = {
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "muted": "#c3c2b7", "edge": "#383835",
             "company": "#3987e5", "sector": "#d95926", "bonds": "#199e70"},
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "muted": "#52514e", "edge": "#c3c2b7",
              "company": "#2a78d6", "sector": "#eb6834", "bonds": "#1baf7a"},
}


def build_graph(table=None) -> nx.Graph:
    """Companies with bonds attributed to them, their sectors and the bonds node."""
    table = connections() if table is None else table
    G = nx.Graph()
    G.add_node(BONDS, kind="bonds", name=BONDS, total=float(table["total"].sum()))
    for key, row in table.iterrows():
        G.add_node(key, kind="company", name=row["name"], sector=row["sector"],
                   total=float(row["total"]), bonds=int(row["bonds"]),
                   first=row["first"].date().isoformat(), last=row["last"].date().isoformat(),
                   purchasers=row["purchasers"], connected=bool(row["connected"]))
        G.add_edge(key, BONDS, kind="bought", total=float(row["total"]))
        if row["sector"]:
            sector = f"sector:{row['sector']}"
            G.add_node(sector, kind="sector", name=row["sector"])
            G.add_edge(key, sector, kind="in_sector")
    return G


def _crore(rupees: float) -> str:
    return f"Rs {rupees / 1e7:,.1f} crore"


def display_name(name: str) -> str:
    """'JINDAL STEEL LIMITED' -> 'Jindal Steel'; 'Vedanta Limited' -> 'Vedanta'."""
    short = re.sub(r"\s+(limited|ltd\.?)$", "", name.strip(), flags=re.I)
    return short.title() if name.isupper() else short


def _size(G: nx.Graph, node: str) -> float:
    data = G.nodes[node]
    if data["kind"] == "company":
        return 8 + 4 * (data["total"] / 1e7) ** 0.5
    return 30 if data["kind"] == "sector" else 45


def save_html(G: nx.Graph, path) -> Path:
    """Interactive graph: drag nodes, hover for details. One self-contained file."""
    from pyvis.network import Network

    theme = THEMES["dark"]
    net = Network(height="750px", width="100%", bgcolor=theme["surface"],
                  font_color=theme["ink"], cdn_resources="in_line")
    net.force_atlas_2based()
    for node, data in G.nodes(data=True):
        kind = data["kind"]
        if kind == "company":
            title = (f"{data['name']}\nSector: {data['sector'] or 'not labelled'}\n"
                     f"{data['bonds']} bonds, {_crore(data['total'])}\n"
                     f"{data['first']} to {data['last']}\nAs listed: {data['purchasers']}")
        elif kind == "sector":
            title = f"Sector: {data['name']}\n{G.degree(node)} companies"
        else:
            title = f"{BONDS}\n{_crore(data['total'])} from {G.degree(node)} listed companies"
        name = display_name(data["name"]) if kind == "company" else data["name"]
        label = name if len(name) <= 20 else name[:17] + "..."
        net.add_node(node, label=label, title=title, color=theme[kind], size=_size(G, node))
    for a, b, data in G.edges(data=True):
        title = _crore(data["total"]) if data["kind"] == "bought" else ""
        net.add_edge(a, b, title=title, color=theme["edge"])

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # vis-network shows string tooltips as plain text on one line; let the
    # line breaks in each title through.
    html = net.generate_html().replace(
        "</head>", "<style>div.vis-tooltip { white-space: pre-line; }</style>\n</head>", 1)
    # Written as UTF-8 here: pyvis's own writer uses the platform encoding.
    path.write_text(html, encoding="utf-8")
    return path


def radial_layout(G: nx.Graph) -> dict:
    """Bonds node at the centre, sectors on an outer ring, each sector's companies
    fanned out on an arc in front of it, and companies without a sector label on
    an inner ring. Deterministic, and companies that share a sector do not stack."""
    def by_total(nodes):
        return sorted(nodes, key=lambda n: (-G.nodes[n]["total"], n))

    companies = [n for n, d in G.nodes(data=True) if d["kind"] == "company"]
    sectors = sorted((n for n, d in G.nodes(data=True) if d["kind"] == "sector"),
                     key=lambda s: (-G.degree(s), s))
    # Alternate large and small sectors around the ring so the big fans get room.
    ring = [s for pair in zip(sectors, reversed(sectors)) for s in pair][:len(sectors)]
    ring = list(dict.fromkeys(ring))
    pos = {BONDS: (0.0, 0.0)}
    step = 2 * math.pi / max(len(ring), 1)
    for i, sector in enumerate(ring):
        angle = math.pi / 2 - i * step
        pos[sector] = (1.05 * math.cos(angle), 1.05 * math.sin(angle))
        members = by_total([n for n in G.neighbors(sector) if n != BONDS])
        # Largest buyers in the middle of the fan, the rest alternating outwards,
        # each on one of three radii so neighbours do not overlap.
        slots = sorted(range(len(members)), key=lambda k: abs(k - (len(members) - 1) / 2))
        width = min(step * 0.9, 0.13 * (len(members) - 1))
        for j, (company, slot) in enumerate(zip(members, slots)):
            a = angle + (slot / max(len(members) - 1, 1) - 0.5) * width
            r = (0.52, 0.68, 0.84)[j % 3]
            pos[company] = (r * math.cos(a), r * math.sin(a))
    loose = by_total([n for n in companies if n not in pos])
    for j, company in enumerate(loose):
        a = math.pi / 2 - 2 * math.pi * j / max(len(loose), 1)
        r = 0.30 if j % 2 == 0 else 0.40
        pos[company] = (r * math.cos(a), r * math.sin(a))
    return pos


def save_png(G: nx.Graph, path, dark: bool = True, labels: int = 7) -> Path:
    """Static rendering for the README, labelling the largest buyers and every sector."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    theme = THEMES["dark" if dark else "light"]
    pos = radial_layout(G)
    fig, ax = plt.subplots(figsize=(11, 9), dpi=150)
    fig.patch.set_facecolor(theme["surface"])
    ax.set_facecolor(theme["surface"])
    ax.axis("off")

    # Marker area in points^2: a company's area is proportional to what it bought.
    def area(node):
        data = G.nodes[node]
        if data["kind"] == "company":
            return 12 + 2.5 * data["total"] / 1e7
        return 260 if data["kind"] == "sector" else 700

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color=theme["edge"], width=0.8)
    for kind in ("company", "sector", "bonds"):
        nodes = [n for n, d in G.nodes(data=True) if d["kind"] == kind]
        if kind == "company":
            nodes.sort(key=lambda n: G.nodes[n]["total"])   # largest last, so on top
        nx.draw_networkx_nodes(G, pos, nodelist=nodes, ax=ax, node_color=theme[kind],
                               node_size=[area(n) for n in nodes],
                               edgecolors=theme["surface"], linewidths=1.5)

    companies = sorted((n for n, d in G.nodes(data=True) if d["kind"] == "company"),
                       key=lambda n: -G.nodes[n]["total"])
    # The largest buyers are numbered inside their own circles and named in a
    # key below, so their names cannot collide however crowded a fan gets.
    top = companies[:labels]
    for rank, node in enumerate(top, 1):
        ax.annotate(str(rank), pos[node], ha="center", va="center", fontsize=7,
                    fontweight="bold", color=theme["surface"])
    for node, data in G.nodes(data=True):
        if data["kind"] == "company":
            continue
        x, y = pos[node]
        gap = (area(node) / math.pi) ** 0.5 + 3
        if node == BONDS:
            offset, ha, va = (0, -gap), "center", "top"
        else:
            # Sectors: label pointing away from the centre.
            angle = math.atan2(y, x)
            offset = (gap * math.cos(angle), gap * math.sin(angle))
            ha = "left" if math.cos(angle) > 0.2 else "right" if math.cos(angle) < -0.2 else "center"
            va = "bottom" if math.sin(angle) > 0.2 else "top" if math.sin(angle) < -0.2 else "center"
        ax.annotate(data["name"], (x, y), xytext=offset, textcoords="offset points", ha=ha, va=va,
                    fontsize=9, fontweight="bold", color=theme["ink"])

    n_companies = len(companies)
    n_labelled = sum(1 for n in companies if G.nodes[n].get("sector"))
    ax.set_title(f"{n_companies} listed companies that bought electoral bonds, by sector",
                 color=theme["ink"], fontsize=13, loc="left", pad=12)
    ax.set_aspect("equal")
    ax.margins(0.12)
    handles = [plt.Line2D([], [], marker="o", linestyle="", markersize=8, color=theme[k], label=t)
               for k, t in (("company", "listed company (area grows with amount bought)"),
                            ("sector", f"sector ({n_labelled} of the {n_companies} have a label)"),
                            ("bonds", BONDS))]
    legend = ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.0),
                       ncol=3, frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(theme["muted"])
    entries = [f"{rank} {display_name(G.nodes[n]['name'])} {G.nodes[n]['total'] / 1e7:,.0f}"
               for rank, n in enumerate(top, 1)]
    half = (len(entries) + 1) // 2
    key = "Largest buyers, Rs crore:   " + "   ".join(entries[:half])
    if entries[half:]:
        key += "\n" + "   ".join(entries[half:])
    ax.text(0.5, -0.07, key, transform=ax.transAxes, ha="center", va="top", fontsize=9,
            color=theme["ink"], linespacing=1.6)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=theme["surface"], bbox_inches="tight")
    plt.close(fig)
    return path
