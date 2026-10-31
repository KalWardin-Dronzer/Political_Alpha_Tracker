"""
The README figures, each in a light and a dark variant.

    python cli.py results      (writes them to results/figures/)
"""

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.connections import connections
from src.data.companies import load_companies
from src.data.price_store import PriceStore
from src.graph import THEMES, build_graph, save_png
from src.research.lead_lag import LeadLagTest
from studies.lead_lag import GRID, SIG_T, pooled_fit
from studies.leadlag_rule import weekly_curves

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans", "sans-serif"]

# Validated categorical slots 1-3 and chart ink, per surface.
SERIES = {"dark": ["#3987e5", "#d95926", "#199e70"], "light": ["#2a78d6", "#eb6834", "#1baf7a"]}
INK = {"dark": {"grid": "#2c2c2a", "axis": "#383835", "muted": "#898781"},
       "light": {"grid": "#e1e0d9", "axis": "#c3c2b7", "muted": "#898781"}}


def _axes(mode: str, figsize=(9, 4.8)):
    t, ink = THEMES[mode], INK[mode]
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(t["surface"])
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(ink["axis"])
    ax.tick_params(colors=t["muted"], length=0)
    ax.yaxis.grid(True, color=ink["grid"], linewidth=1)
    ax.set_axisbelow(True)
    return fig, ax, t


def _save(fig, path: Path, surface: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=surface, bbox_inches="tight")
    plt.close(fig)
    return path


def lead_lag_chart(rows: list[dict], mode: str, path: Path) -> Path:
    """t-statistics of the treatment and placebo arms for each pre-declared spec."""
    fig, ax, t = _axes(mode)
    blue, orange, _ = SERIES[mode]
    x = range(len(rows))
    width = 0.34
    for i, (arm, color, label) in enumerate((("treatment", blue, "Bond buyers lead peers"),
                                              ("placebo", orange, "Size-matched non-buyers lead peers"))):
        offset = (i - 0.5) * (width + 0.02)
        bars = ax.bar([v + offset for v in x], [r[arm] for r in rows], width=width,
                      color=color, label=label)
        for bar, r in zip(bars, rows):
            value = r[arm]
            ax.annotate(f"{value:.2f}", (bar.get_x() + bar.get_width() / 2, value),
                        xytext=(0, 3 if value >= 0 else -11), textcoords="offset points",
                        ha="center", fontsize=8, color=t["muted"])
    ax.axhline(SIG_T, color=INK[mode]["muted"], linewidth=1)
    ax.annotate(f"t = {SIG_T:g}, nominal significance", (len(rows) - 0.5, SIG_T),
                xytext=(0, 4), textcoords="offset points", ha="right", fontsize=8, color=t["muted"])
    ax.axhline(0, color=INK[mode]["axis"], linewidth=1)
    ax.set_xticks(list(x), [r["label"] for r in rows], color=t["ink"])
    ax.set_ylabel("t-statistic (clustered by period)", color=t["muted"])
    ax.set_title("Bond buyers do not lead their peers; size-matched non-buyers do at weekly lag 1",
                 color=t["ink"], loc="left", fontsize=12, pad=30)
    legend = ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2,
                       fontsize=9, borderaxespad=0.2)
    for text in legend.get_texts():
        text.set_color(t["ink"])
    return _save(fig, path, t["surface"])


def _sharpe(weekly) -> float:
    weekly = weekly.dropna()
    return float(weekly.mean() / weekly.std() * 52 ** 0.5)


def rule_chart(curves, mode: str, path: Path) -> Path:
    """Growth of Rs 1 for the weekly rule gross and net of costs, and for buy-and-hold."""
    fig, ax, t = _axes(mode)
    sharpe = {column: _sharpe(curves[column]) for column in curves}
    blue, orange, aqua = SERIES[mode]
    growth = (1 + curves.fillna(0)).cumprod()
    for column, color, label in (("gross", blue, "Rule, before costs"),
                                 ("net", orange, "Rule, after costs"),
                                 ("buy_and_hold", aqua, "Buy and hold the same stocks")):
        series = growth[column]
        ax.plot(series.index, series.values, color=color, linewidth=2,
                solid_capstyle="round", label=label)
        ax.annotate(f"{label}: {series.iloc[-1]:.2f}x, Sharpe {sharpe[column]:.2f}",
                    (series.index[-1], series.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=8, color=t["ink"])
    ax.set_ylabel("Growth of Rs 1", color=t["muted"])
    ax.set_title(f"Weekly lead-lag rule: Sharpe {sharpe['gross']:.2f} before costs, "
                 f"{sharpe['net']:.2f} after; buy-and-hold {sharpe['buy_and_hold']:.2f}",
                 color=t["ink"], loc="left", fontsize=12, pad=12)
    legend = ax.legend(frameon=False, loc="upper left", fontsize=9)
    for text in legend.get_texts():
        text.set_color(t["ink"])
    return _save(fig, path, t["surface"])


def lead_lag_rows(store, companies, connected) -> list[dict]:
    """Treatment and placebo t-statistics for each specification in the grid."""
    test = LeadLagTest(store, companies, connected)
    groups = test.build_groups()
    rows = []
    for freq, label, lag in GRID:
        fit = pooled_fit(test, groups, freq, lag)
        rows.append({"label": f"{label}, lag {lag}",
                     "treatment": fit["treatment"]["t"], "placebo": fit["placebo"]["t"]})
    return rows


def save_all(directory) -> list[Path]:
    directory = Path(directory)
    store, companies = PriceStore(), load_companies()
    table = connections()
    connected = set(table.index[table["connected"]])
    rows = lead_lag_rows(store, companies, connected)
    curves = weekly_curves(store)
    graph = build_graph(table)
    written = []
    for mode in ("light", "dark"):
        written.append(save_png(graph, directory / f"connections-{mode}.png", dark=mode == "dark"))
        written.append(lead_lag_chart(rows, mode, directory / f"lead-lag-{mode}.png"))
        written.append(rule_chart(curves, mode, directory / f"leadlag-rule-{mode}.png"))
    return written


if __name__ == "__main__":
    for p in save_all(Path(_ROOT) / "results" / "figures"):
        print(p)
