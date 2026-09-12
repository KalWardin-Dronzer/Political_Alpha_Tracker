"""
Test the peer lead-lag hypothesis on the political graph.

    python scripts/research/run_lead_lag.py
    python cli.py research lead-lag

THE HYPOTHESIS
--------------
Kim, Kim, Pantzalis & Park (Financial Analysts Journal, 2018) report that
returns of politically connected firms LEAD those of their non-connected peers:
political information reaches connected prices first and comparable competitors'
prices later. If it holds on NSE, the tradeable leg is the PEER, not the
connected winner — the opposite of what this project was built to do.

WHY EVERY REGRESSION RUNS TWICE
-------------------------------
Connected firms here are mostly large, liquid names. Large-cap returns are known
to lead small-cap returns for liquidity and information-diffusion reasons alone,
so the naive regression would produce a positive coefficient whether or not
politics has anything to do with it.

  TREATMENT  peers ~ lagged CONNECTED returns
  PLACEBO    peers ~ lagged size-matched UNCONNECTED returns

Placebo leaders come from the same sector and are matched on traded value, so
they resemble the connected group in everything but the political connection. If
the two coefficients are similar, the lead-lag is a size effect.

STANDARD ERRORS ARE CLUSTERED BY PERIOD, NOT JUST HAC
-----------------------------------------------------
The sector baskets share the same calendar dates, so pooled observations are not
independent. HAC alone overstated significance here: monthly lag-2 read t=2.84
under HAC and t=2.36 once clustered. Clustering is the honest number.

THE GRID IS FIXED IN THIS FILE
------------------------------
Four specifications, all reported, none dropped. Searching frequencies and lags
until one looks good and reporting only that is how a null becomes a discovery.

RESULT ON RECORD (2026-09-12, 64-company graph)
-----------------------------------------------
0 of 4 specifications significant. Monthly lag-2 — which read beta 0.18,
t 2.36, p 0.019 on the earlier 20-company graph, with stable split-halves — fell
to beta 0.08, t 0.87, p 0.38. Meanwhile the PLACEBO became significant at weekly
lag-1 (beta 0.089, t 2.87).

That is the cleanest available refutation: the diffusion mechanism is real, it is
size and liquidity, and political connection adds nothing on top of it. A genuine
effect strengthens as power rises; this one dissolved when the connected group
grew from 18 to 30 companies on a graph with false matches removed.
"""

import logging
import sys

# Allow running this file directly as well as through cli.py.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import pandas as pd
import statsmodels.api as sm

from src.data.cache_manager import CacheManager
from src.data.price_store import PriceStore
from src.signals.graph_manager import GraphManager
from src.signals.lead_lag import LeadLagTest

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("lead_lag")

# Pre-declared. Do not edit between runs to chase a result.
GRID = [("W-FRI", "weekly", 1), ("W-FRI", "weekly", 2),
        ("ME", "monthly", 1), ("ME", "monthly", 2)]

SIG_T = 2.0


def pooled_fit(t: LeadLagTest, groups, freq: str, lag: int):
    """
    Pool sector-period observations and fit both arms with period-clustered SEs.

    Baskets are demeaned within sector so a sector with persistently higher
    returns cannot masquerade as a lead-lag relationship.
    """
    rets = t._returns(freq)
    market = rets.mean(axis=1)

    frames = []
    for g in groups:
        conn = t._basket(rets, g.connected)
        plac = t._basket(rets, g.placebo)
        peer = t._basket(rets, g.peers)
        if conn.empty or plac.empty or peer.empty:
            continue
        df = pd.DataFrame({
            "peer": peer - peer.mean(),
            "conn_lag": (conn - conn.mean()).shift(lag),
            "plac_lag": (plac - plac.mean()).shift(lag),
            "peer_lag": (peer - peer.mean()).shift(lag),
            "mkt_lag": (market - market.mean()).shift(lag),
        }).dropna()
        df["date"] = df.index
        frames.append(df)
    if not frames:
        return None

    pool = pd.concat(frames)
    out = {"rows": len(pool), "periods": pool["date"].nunique()}
    for col, arm in (("conn_lag", "treatment"), ("plac_lag", "placebo")):
        X = sm.add_constant(pool[[col, "peer_lag", "mkt_lag"]])
        fit = sm.OLS(pool["peer"], X).fit(
            cov_type="cluster", cov_kwds={"groups": pool["date"].values})
        out[arm] = {"beta": float(fit.params[col]),
                    "t": float(fit.tvalues[col]),
                    "p": float(fit.pvalues[col])}
    return out


def main():
    cache = CacheManager()
    graph = GraphManager(cache)
    graph.build_from_cache()
    store = PriceStore()
    if store.close().empty:
        logger.error("Price panel empty. Run: python cli.py prices")
        return 1

    t = LeadLagTest(store, cache, graph)
    groups = t.build_groups()
    if not groups:
        logger.error("No sector has enough connected companies AND peers. "
                     "Sector coverage is the usual cause — check `cli.py health`.")
        return 1

    n_conn = sum(len(g.connected) for g in groups)
    n_peer = sum(len(g.peers) for g in groups)
    print(f"graph: {graph.G.number_of_nodes()} nodes, {graph.G.number_of_edges()} edges")
    print(f"usable sectors: {len(groups)}   connected in test: {n_conn}   peers: {n_peer}")
    for g in groups:
        print(f"  {g.sector:26} connected={len(g.connected):>2} "
              f"placebo={len(g.placebo):>2} peers={len(g.peers):>2}")

    print()
    print("PRE-DECLARED GRID — clustered by period, all specifications reported")
    print(f"{'freq':>8}{'lag':>5}{'rows':>7}{'periods':>9}"
          f"{'treat b':>10}{'treat t':>9}{'treat p':>9}{'plac b':>9}{'plac t':>8}")
    print("-" * 84)

    positive_sig = []
    for freq, label, lag in GRID:
        r = pooled_fit(t, groups, freq, lag)
        if r is None:
            print(f"{label:>8}{lag:>5}   insufficient data")
            continue
        tr, pl = r["treatment"], r["placebo"]
        print(f"{label:>8}{lag:>5}{r['rows']:>7}{r['periods']:>9}"
              f"{tr['beta']:>10.4f}{tr['t']:>9.2f}{tr['p']:>9.4f}"
              f"{pl['beta']:>9.4f}{pl['t']:>8.2f}")
        if tr["t"] >= SIG_T and tr["beta"] > 0:
            positive_sig.append((label, lag, tr["p"], pl["t"]))

    print()
    print(f"specifications significant AND positive: {len(positive_sig)}/{len(GRID)}")
    if not positive_sig:
        print("  VERDICT: no political lead-lag. If the PLACEBO column shows")
        print("  significance where the treatment does not, the diffusion is a size")
        print("  and liquidity effect and political connection adds nothing.")
    else:
        best_p = min(p for _, _, p, _ in positive_sig)
        print(f"  best nominal p = {best_p:.4f}   "
              f"Bonferroni x{len(GRID)} = {best_p*len(GRID):.4f}   (bar 0.05)")
        if best_p * len(GRID) >= 0.05:
            print("  VERDICT: does not survive correction for four specifications.")
        else:
            print("  VERDICT: survives correction — check the placebo arm before")
            print("  believing it, and re-run on a larger connected set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
