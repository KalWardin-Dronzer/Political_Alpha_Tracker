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

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.connections import connections
from src.data.companies import load_companies
from src.data.price_store import PriceStore
from src.graph import THEMES, build_graph, save_png
from src.research.lead_lag import LeadLagTest
from studies.lead_lag import GRID, pooled_fit
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
    """Treatment, placebo and their difference for each pre-declared spec, with 95% intervals."""
    fig, ax, t = _axes(mode, figsize=(9, 5.2))
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=INK[mode]["grid"], linewidth=1)
    blue, orange, aqua = SERIES[mode]
    arms = (("treatment", blue, "Bond buyers lead peers"),
            ("placebo", orange, "Size-matched non-buyers lead peers"),
            ("difference", aqua, "Bond buyers minus non-buyers"))
    for i, (arm, color, label) in enumerate(arms):
        for j, r in enumerate(rows):
            y = j + (i - 1) * 0.24
            est = r[arm]
            ax.plot([est["lo"], est["hi"]], [y, y], color=color, linewidth=2.2, solid_capstyle="round")
            ax.plot(est["beta"], y, "o", color=color, markersize=6, label=label if j == 0 else None)
    ax.axvline(0, color=INK[mode]["axis"], linewidth=1)
    ax.set_yticks(range(len(rows)), [r["label"] for r in rows], color=t["ink"])
    ax.invert_yaxis()
    ax.set_xlabel("coefficient on the lagged leader basket (95% interval, clustered by period)", color=t["muted"])
    ax.set_title("Peer lead-lag: bond buyers, size-matched non-buyers and the difference",
                 color=t["ink"], loc="left", fontsize=12, pad=30)
    legend = ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3,
                       fontsize=9, borderaxespad=0.2)
    for text in legend.get_texts():
        text.set_color(t["ink"])
    return _save(fig, path, t["surface"])


def event_chart(result: dict, mode: str, path: Path) -> Path:
    """Cumulative abnormal return of buyers minus matched controls around each event, with 95% bands."""
    import numpy as np
    from scipy import stats as st
    from src.research.event_study import EVENTS

    t_ = THEMES[mode]
    fig, axes = plt.subplots(1, len(EVENTS), figsize=(11, 3.8), dpi=150, sharey=True)
    fig.patch.set_facecolor(t_["surface"])
    blue = SERIES[mode][0]
    abnormal, sigma = result["abnormal"], result["sigma"]
    q = st.t.ppf(0.975, result["estimation_days"] - 1)
    days = np.arange(-10, 11)
    for ax, event in zip(axes, EVENTS):
        ax.set_facecolor(t_["surface"])
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(INK[mode]["axis"])
        ax.tick_params(colors=t_["muted"], length=0)
        ax.yaxis.grid(True, color=INK[mode]["grid"], linewidth=1)
        at = abnormal.index.get_loc(pd.Timestamp(event.day0))
        path_ = 100 * abnormal.iloc[at - 10: at + 11].cumsum().to_numpy()
        band = 100 * q * sigma * np.sqrt(np.arange(1, 22))
        ax.fill_between(days, -band, band, color=INK[mode]["grid"], linewidth=0)
        ax.plot(days, path_, color=blue, linewidth=2)
        ax.axvline(0, color=INK[mode]["muted"], linewidth=1, linestyle="--")
        ax.axhline(0, color=INK[mode]["axis"], linewidth=1)
        ax.set_title(f"{event.label}\n(day 0 = {event.day0})", color=t_["ink"], fontsize=9, loc="left")
        ax.set_xlabel("trading days", color=t_["muted"], fontsize=8)
    axes[0].set_ylabel("cumulative abnormal return, % (from day -10)", color=t_["muted"], fontsize=8)
    fig.suptitle("Bond buyers minus matched non-buyers; shaded: 95% band under no reaction",
                 color=t_["ink"], fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    return _save(fig, path, t_["surface"])


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
    """Treatment, placebo and difference estimates for each specification in the grid."""
    test = LeadLagTest(store, companies, connected)
    groups = test.build_groups()
    rows = []
    for freq, label, lag in GRID:
        fit = pooled_fit(test, groups, freq, lag)
        rows.append({"label": f"{label}, lag {lag}",
                     **{arm: fit[arm] for arm in ("treatment", "placebo", "difference")}})
    return rows


def save_all(directory) -> list[Path]:
    from src.research.event_study import EventStudy

    directory = Path(directory)
    store, companies = PriceStore(), load_companies()
    table = connections()
    connected = set(table.index[table["connected"]])
    rows = lead_lag_rows(store, companies, connected)
    event = EventStudy(store.close(), store.volume(), companies, connected).run()
    curves = weekly_curves(store)
    graph = build_graph(table)
    written = []
    for mode in ("light", "dark"):
        written.append(save_png(graph, directory / f"connections-{mode}.png", dark=mode == "dark"))
        written.append(lead_lag_chart(rows, mode, directory / f"lead-lag-{mode}.png"))
        written.append(event_chart(event, mode, directory / f"event-study-{mode}.png"))
        written.append(rule_chart(curves, mode, directory / f"leadlag-rule-{mode}.png"))
    return written


if __name__ == "__main__":
    for p in save_all(Path(_ROOT) / "results" / "figures"):
        print(p)
