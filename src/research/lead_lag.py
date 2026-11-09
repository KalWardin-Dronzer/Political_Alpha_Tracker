"""
Peer lead-lag test.

THE HYPOTHESIS
--------------
Kim, Kim, Pantzalis & Park (Financial Analysts Journal, 2018) report that
returns of politically connected firms LEAD those of their non-connected peers:
political information reaches connected firms' prices first and arrives in
comparable competitors' prices with a delay. Their stated implication is that
you can predict the unconnected company by watching the connected one.

Here "connected" means the company bought electoral bonds (src.connections).

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
connection. Political connection adds something only if the treatment
coefficient exceeds the placebo's by more than chance allows, which
studies/lead_lag.py tests directly; a significant placebo next to an
insignificant treatment is not, by itself, evidence that the two differ.

Placebo leaders are removed from the peer group, since a group cannot be used
to predict itself.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.companies import company_key

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


class LeadLagTest:
    """
    Sector groups and their equal-weight return baskets; studies/lead_lag.py
    runs the regressions on them.

        t = LeadLagTest(price_store, companies, connected)
        groups = t.build_groups()

    `companies` is the universe table (data/companies.csv) and `connected` the
    set of company keys that bought electoral bonds (src.connections).
    """

    def __init__(self, price_store, companies: pd.DataFrame, connected: set[str]):
        self.store = price_store
        self.companies = companies
        self.connected = set(connected)

    # ──────────────────────────────────────────
    # Group construction
    # ──────────────────────────────────────────
    def build_groups(self, min_adv_cr: float = 0.5, adv=None) -> list[SectorGroups]:
        """
        Split each sector into connected / placebo-leader / peer groups.

        Placebo leaders are the unconnected names whose traded value most
        closely matches the connected group's median, so they stand in for
        "a comparably large and liquid name that simply isn't connected".

        `adv` is the traded value per symbol (Rs crore) used for the liquidity
        screen and the matching. The declared default is the panel's last 252
        sessions, which judges liquidity after the fact; the study also runs a
        check with the panel's first year.
        """
        panel = set(self.store.close().columns)
        adv = self.store.adv_cr(252) if adv is None else adv

        by_sector: dict[str, dict[str, list]] = {}
        for _, r in self.companies.iterrows():
            sym = r["nse_symbol"]
            if not sym or not r["sector"] or sym not in panel:
                continue
            if adv.get(sym, 0.0) < min_adv_cr:
                continue
            connected = company_key(r) in self.connected
            slot = by_sector.setdefault(r["sector"], {"connected": [], "unconnected": []})
            slot["connected" if connected else "unconnected"].append(sym)

        out = []
        for sector, d in sorted(by_sector.items()):
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
