"""
Political Alpha Tracker — Peer Lead-Lag Test

THE HYPOTHESIS
--------------
Kim, Kim, Pantzalis & Park (Financial Analysts Journal, 2018) report that
returns of politically connected firms LEAD those of their non-connected peers:
political information reaches connected firms' prices first and arrives in
comparable competitors' prices with a delay. Their stated implication is that
you can predict the unconnected company by watching the connected one.

If that holds on NSE, the tradeable leg is the PEER, not the connected winner —
the opposite of what this project was built to do, and consistent with its own
(underpowered) event study, where unconnected peers beat connected names at
every horizon.

WHY THIS TEST IS SHAPED THE WAY IT IS
-------------------------------------
The obvious version — regress peer returns on lagged connected returns — will
produce a positive coefficient whether or not politics has anything to do with
it. Connected firms here are mostly large, liquid names (Maruti, Hero MotoCorp,
Lupin, Divi's, UPL, Vedanta), and large-cap returns are known to lead small-cap
returns for reasons of liquidity and information diffusion alone (Lo &
MacKinlay). A naive positive result would simply rediscover that.

So every regression is run twice:

  TREATMENT  peers ~ lagged CONNECTED returns
  PLACEBO    peers ~ lagged UNCONNECTED-BUT-COMPARABLE returns

The placebo leaders are drawn from the same sector and matched on traded value,
so they resemble the connected group in everything except the political
connection. If the two coefficients are similar, the lead-lag is a size and
liquidity effect and the political graph adds nothing. This is the same logic
as the random-selection control that settled the factor model.

Placebo leaders are removed from the peer group, since a group cannot be used
to predict itself.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_CONNECTED = 2        # need a basket, not a single name
MIN_PEERS = 4            # after removing placebo leaders
DEFAULT_FREQ = "W-FRI"   # weekly, Friday close


@dataclass
class SectorGroups:
    sector: str
    connected: list[str]
    placebo: list[str]
    peers: list[str]

    def usable(self) -> bool:
        return (len(self.connected) >= MIN_CONNECTED
                and len(self.peers) >= MIN_PEERS
                and len(self.placebo) >= 1)


@dataclass
class LeadLagResult:
    scope: str
    n_obs: int
    treatment_beta: float
    treatment_t: float
    placebo_beta: float
    placebo_t: float
    treatment_r2: float
    placebo_r2: float
    detail: dict = field(default_factory=dict)

    @property
    def excess_beta(self) -> float:
        """How much more the connected group predicts than a matched control."""
        return self.treatment_beta - self.placebo_beta

    def verdict(self) -> str:
        if self.treatment_t < 2.0:
            return "NO LEAD-LAG (connected group does not predict peers)"
        if self.placebo_t >= 2.0 and abs(self.excess_beta) < 0.15:
            return "SIZE EFFECT (matched control predicts just as well)"
        if self.excess_beta > 0.15 and self.treatment_t >= 2.0:
            return "POLITICAL LEAD-LAG SURVIVES THE CONTROL"
        return "AMBIGUOUS"

    def summary(self) -> dict:
        return {
            "scope": self.scope,
            "n_obs": self.n_obs,
            "treatment_beta": round(self.treatment_beta, 4),
            "treatment_t": round(self.treatment_t, 2),
            "placebo_beta": round(self.placebo_beta, 4),
            "placebo_t": round(self.placebo_t, 2),
            "excess_beta": round(self.excess_beta, 4),
            "treatment_r2": round(self.treatment_r2, 4),
            "placebo_r2": round(self.placebo_r2, 4),
            "verdict": self.verdict(),
        }


def _ols_hac(y: pd.Series, X: pd.DataFrame, lags: int = 4):
    """
    OLS with Newey-West (HAC) standard errors.

    Plain OLS t-stats overstate significance on overlapping, autocorrelated
    return series, which is how weak lead-lag findings get published.
    """
    import statsmodels.api as sm
    Xc = sm.add_constant(X, has_constant="add")
    frame = pd.concat([y, Xc], axis=1).dropna()
    if len(frame) < 30:
        return None
    yy = frame.iloc[:, 0]
    XX = frame.iloc[:, 1:]
    return sm.OLS(yy, XX).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


class LeadLagTest:
    """
        t = LeadLagTest(price_store, cache, graph)
        groups = t.build_groups()
        pooled = t.run_pooled(groups)
    """

    def __init__(self, price_store, cache, graph):
        self.store = price_store
        self.cache = cache
        self.graph = graph

    # ──────────────────────────────────────────
    # Group construction
    # ──────────────────────────────────────────
    def build_groups(self, min_adv_cr: float = 0.5) -> list[SectorGroups]:
        """
        Split each sector into connected / placebo-leader / peer groups.

        Placebo leaders are the unconnected names whose traded value most
        closely matches the connected group's median, so they stand in for
        "a comparably large and liquid name that simply isn't connected".
        """
        panel = set(self.store.close().columns)
        adv = self.store.adv_cr(252)

        with self.cache._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT nse_symbol, name, sector, cin FROM companies "
                "WHERE sector IS NOT NULL AND sector != '' "
                "AND nse_symbol IS NOT NULL AND nse_symbol != ''"
            ).fetchall()]

        by_sector: dict[str, dict[str, list]] = {}
        for r in rows:
            sym = r["nse_symbol"]
            if sym not in panel:
                continue
            if adv.get(sym, 0.0) < min_adv_cr:
                continue
            cin = r.get("cin")
            connected = bool(cin) and bool(self.graph.alpha_query(cin))
            slot = by_sector.setdefault(r["sector"], {"connected": [], "unconnected": []})
            slot["connected" if connected else "unconnected"].append(sym)

        out = []
        for sector, d in by_sector.items():
            conn_syms = sorted(set(d["connected"]))
            unconn = sorted(set(d["unconnected"]))
            if len(conn_syms) < MIN_CONNECTED or len(unconn) < MIN_PEERS + 1:
                continue

            # Match placebo leaders to the connected group's median traded value.
            target = float(np.median([adv.get(s, 0.0) for s in conn_syms]))
            ranked = sorted(unconn, key=lambda s: abs(adv.get(s, 0.0) - target))
            k = min(len(conn_syms), max(1, len(unconn) - MIN_PEERS))
            placebo = ranked[:k]
            peers = [s for s in unconn if s not in set(placebo)]

            g = SectorGroups(sector, conn_syms, placebo, peers)
            if g.usable():
                out.append(g)

        return out

    # ──────────────────────────────────────────
    # Return series
    # ──────────────────────────────────────────
    def _returns(self, freq: str = DEFAULT_FREQ) -> pd.DataFrame:
        px = self.store.close()
        px.index = pd.to_datetime(px.index)
        periodic = px.resample(freq).last()
        return periodic.pct_change()

    def _basket(self, rets: pd.DataFrame, syms: list[str]) -> pd.Series:
        cols = [s for s in syms if s in rets.columns]
        if not cols:
            return pd.Series(dtype=float)
        return rets[cols].mean(axis=1)

    # ──────────────────────────────────────────
    # Tests
    # ──────────────────────────────────────────
    def run_sector(self, g: SectorGroups, freq: str = DEFAULT_FREQ,
                   lag: int = 1) -> Optional[LeadLagResult]:
        rets = self._returns(freq)
        market = rets.mean(axis=1)

        conn = self._basket(rets, g.connected)
        plac = self._basket(rets, g.placebo)
        peer = self._basket(rets, g.peers)
        if conn.empty or plac.empty or peer.empty:
            return None

        base = pd.DataFrame({
            "peer_lag": peer.shift(lag),       # peers' own autocorrelation
            "mkt_lag": market.shift(lag),      # general market lead-lag
        })

        t_fit = _ols_hac(peer.rename("peer"),
                         base.assign(lead=conn.shift(lag)))
        p_fit = _ols_hac(peer.rename("peer"),
                         base.assign(lead=plac.shift(lag)))
        if t_fit is None or p_fit is None:
            return None

        return LeadLagResult(
            scope=g.sector,
            n_obs=int(t_fit.nobs),
            treatment_beta=float(t_fit.params["lead"]),
            treatment_t=float(t_fit.tvalues["lead"]),
            placebo_beta=float(p_fit.params["lead"]),
            placebo_t=float(p_fit.tvalues["lead"]),
            treatment_r2=float(t_fit.rsquared),
            placebo_r2=float(p_fit.rsquared),
            detail={
                "n_connected": len(g.connected),
                "n_placebo": len(g.placebo),
                "n_peers": len(g.peers),
                "connected": g.connected,
                "placebo": g.placebo,
            },
        )

    def run_pooled(self, groups: list[SectorGroups], freq: str = DEFAULT_FREQ,
                   lag: int = 1) -> Optional[LeadLagResult]:
        """
        Pool sector-period observations into one regression.

        Each sector alone has only a few hundred weekly observations; pooling
        buys the power to distinguish a real coefficient from a noisy one.
        Sector baskets are demeaned within sector so a sector with persistently
        higher returns cannot masquerade as a lead-lag relationship.
        """
        rets = self._returns(freq)
        market = rets.mean(axis=1)

        frames = []
        for g in groups:
            conn = self._basket(rets, g.connected)
            plac = self._basket(rets, g.placebo)
            peer = self._basket(rets, g.peers)
            if conn.empty or plac.empty or peer.empty:
                continue
            df = pd.DataFrame({
                "peer": peer - peer.mean(),
                "conn_lag": (conn - conn.mean()).shift(lag),
                "plac_lag": (plac - plac.mean()).shift(lag),
                "peer_lag": (peer - peer.mean()).shift(lag),
                "mkt_lag": (market - market.mean()).shift(lag),
            }).dropna()
            df["sector"] = g.sector
            frames.append(df)

        if not frames:
            return None
        pool = pd.concat(frames, axis=0)

        t_fit = _ols_hac(pool["peer"], pool[["conn_lag", "peer_lag", "mkt_lag"]]
                         .rename(columns={"conn_lag": "lead"}))
        p_fit = _ols_hac(pool["peer"], pool[["plac_lag", "peer_lag", "mkt_lag"]]
                         .rename(columns={"plac_lag": "lead"}))
        if t_fit is None or p_fit is None:
            return None

        return LeadLagResult(
            scope=f"POOLED ({len(frames)} sectors)",
            n_obs=int(t_fit.nobs),
            treatment_beta=float(t_fit.params["lead"]),
            treatment_t=float(t_fit.tvalues["lead"]),
            placebo_beta=float(p_fit.params["lead"]),
            placebo_t=float(p_fit.tvalues["lead"]),
            treatment_r2=float(t_fit.rsquared),
            placebo_r2=float(p_fit.rsquared),
            detail={"sectors": [g.sector for g in groups]},
        )
