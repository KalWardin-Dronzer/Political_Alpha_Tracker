"""
Test the peer lead-lag hypothesis on companies that bought electoral bonds.

    python cli.py study lead-lag

THE HYPOTHESIS
--------------
Kim, Kim, Pantzalis & Park (Financial Analysts Journal, 2018) report that
returns of politically connected firms LEAD those of their non-connected peers:
political information reaches connected prices first and comparable competitors'
prices later. If it holds on NSE, the tradeable leg is the PEER, not the
connected winner.

TWO ARMS, AND A TEST OF THE DIFFERENCE
--------------------------------------
Connected firms here are mostly large, liquid names, and large-cap returns lead
small-cap returns for liquidity reasons alone, so each specification is fitted
for two leaders:

  TREATMENT  peers ~ lagged CONNECTED returns
  PLACEBO    peers ~ lagged size-matched UNCONNECTED returns

Whether political connection adds anything is a question about the DIFFERENCE
between the two coefficients, so it is tested directly: both arms are stacked in
one fully interacted regression, clustered by period, whose interaction term is
the treatment coefficient minus the placebo coefficient, with a standard error
that accounts for the two arms sharing their dates. An earlier version read
"the placebo is significant and the treatment is not" as "the effect is size,
not politics"; a difference in significance is not a significant difference.

STANDARD ERRORS ARE CLUSTERED BY PERIOD
---------------------------------------
The sector baskets share the same calendar dates, so pooled observations are not
independent. Every coefficient's standard error is clustered by date.

POWER
-----
Each estimate is reported with its minimum detectable effect: the true
coefficient this test would detect with 80% probability at the 5% level,
(1.96 + 0.84) x its standard error. A non-significant result says little about
effects smaller than that.

THE GRID AND THE DECISION RULES ARE FIXED IN THIS FILE (declared 2026-11-09,
before the rebuilt data were run)
---------------------------------------------------------------------------
Four specifications, all reported. Political connection is said to
- LEAD peers if the treatment coefficient is positive with a Holm-adjusted
  two-sided p below 0.05 in at least one specification;
- add to the size effect if the treatment-minus-placebo difference is positive
  with a Holm-adjusted two-sided p below 0.05 in at least one specification.
Otherwise the result is "no evidence", stated with the 95% intervals. The
primary definition of a connected company is group level (src.connections);
entity level is reported as a check.

ADDED AFTER THE FIRST RUN (2026-11-09)
--------------------------------------
The declared design screens and size-matches companies on traded value over
the panel's last year, which judges liquidity after the fact. A second check,
added after the first run and not part of the decision rules, repeats the group
level with traded value over the panel's first year (2019) instead. The price
panel itself is now cleaned of impossible daily moves (src.data.price_store);
the first run, on uncleaned prices, is in the git history (commit ce5f11f).
"""

import logging
import sys

# Allow running this file directly as well as through cli.py.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from src.connections import connections
from src.data.companies import load_companies
from src.data.price_store import PriceStore
from src.research.lead_lag import LeadLagTest

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("lead_lag")

# Pre-declared. Do not edit between runs to chase a result.
GRID = [("W-FRI", "weekly", 1), ("W-FRI", "weekly", 2),
        ("ME", "monthly", 1), ("ME", "monthly", 2)]
ALPHA = 0.05
MDE_Z = 1.96 + 0.8416   # 5% two-sided test, 80% power
LEVELS = ("group", "entity")
FIRST_YEAR_END = "2019-12-31"   # for the check added after the first run


def _pool(t: LeadLagTest, groups, freq: str, lag: int) -> pd.DataFrame | None:
    """Sector-period observations, baskets demeaned within sector so a sector with
    persistently higher returns cannot masquerade as a lead-lag relationship."""
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
    return pd.concat(frames) if frames else None


def _estimate(fit, term: str) -> dict:
    beta, se = float(fit.params[term]), float(fit.bse[term])
    return {"beta": beta, "se": se, "t": float(fit.tvalues[term]), "p": float(fit.pvalues[term]),
            "lo": beta - 1.96 * se, "hi": beta + 1.96 * se, "mde": MDE_Z * se}


def stacked_difference(pool: pd.DataFrame):
    """Both arms in one regression, every coefficient interacted with the arm, clustered by date.

    The coefficient on `lead` is the placebo arm's and `lead_x_treat` is treatment
    minus placebo; the point estimates equal the two separate fits.
    """
    arms = []
    for col, treat in (("conn_lag", 1.0), ("plac_lag", 0.0)):
        arms.append(pd.DataFrame({
            "peer": pool["peer"], "date": pool["date"], "treat": treat,
            "lead": pool[col], "peer_lag": pool["peer_lag"], "mkt_lag": pool["mkt_lag"],
        }))
    long = pd.concat(arms, ignore_index=True)
    X = pd.DataFrame({
        "const": 1.0, "treat": long["treat"],
        "lead": long["lead"], "lead_x_treat": long["lead"] * long["treat"],
        "peer_lag": long["peer_lag"], "peer_lag_x_treat": long["peer_lag"] * long["treat"],
        "mkt_lag": long["mkt_lag"], "mkt_lag_x_treat": long["mkt_lag"] * long["treat"],
    })
    return sm.OLS(long["peer"], X).fit(cov_type="cluster", cov_kwds={"groups": long["date"].values})


def pooled_fit(t: LeadLagTest, groups, freq: str, lag: int):
    """Treatment, placebo and their difference for one specification, clustered by period."""
    pool = _pool(t, groups, freq, lag)
    if pool is None:
        return None
    out = {"rows": len(pool), "periods": pool["date"].nunique()}
    for col, arm in (("conn_lag", "treatment"), ("plac_lag", "placebo")):
        X = sm.add_constant(pool[[col, "peer_lag", "mkt_lag"]])
        fit = sm.OLS(pool["peer"], X).fit(cov_type="cluster", cov_kwds={"groups": pool["date"].values})
        out[arm] = _estimate(fit, col)
    out["difference"] = _estimate(stacked_difference(pool), "lead_x_treat")
    return out


def main():
    store = PriceStore()
    if store.close().empty:
        logger.error("Price panel empty. Run: python cli.py prices")
        return 1
    companies = load_companies()
    for level in LEVELS:
        table = connections(level=level)
        connected = set(table.index[table["connected"]])
        print(f"=== {level.upper()} LEVEL{' (primary)' if level == LEVELS[0] else ' (check)'}: "
              f"{len(connected)} connected companies (a bond of Rs 10 lakh or more)")
        code = report(store, companies, connected)
        if code:
            return code
        print()

    first_year = store.adv_cr(252, as_of=FIRST_YEAR_END)
    table = connections(level=LEVELS[0])
    print("=== GROUP LEVEL, liquidity judged on 2019 traded value (check added after the first run)")
    return report(store, companies, set(table.index[table["connected"]]), adv=first_year)


def report(store, companies, connected, adv=None) -> int:
    """Run the pre-declared grid for one definition of `connected` and print it."""
    t = LeadLagTest(store, companies, connected)
    groups = t.build_groups(adv=adv)
    if not groups:
        logger.error("No sector has enough connected companies AND peers.")
        return 1

    n_conn = sum(len(g.connected) for g in groups)
    n_plac = sum(len(g.placebo) for g in groups)
    n_peer = sum(len(g.peers) for g in groups)
    print(f"usable sectors: {len(groups)}   connected in test: {n_conn}   placebo leaders: {n_plac}   peers: {n_peer}")
    for g in groups:
        print(f"  {g.sector:28} connected={len(g.connected):>3} placebo={len(g.placebo):>3} peers={len(g.peers):>3}")

    print()
    print("PRE-DECLARED GRID: coefficients with 95% intervals, clustered by period")
    print(f"{'spec':>12}{'periods':>8}  {'treatment':>26}  {'placebo':>26}  {'treatment - placebo':>28}  {'MDE treat':>9}")
    print("-" * 118)
    fits = []
    for freq, label, lag in GRID:
        r = pooled_fit(t, groups, freq, lag)
        if r is None:
            print(f"{label + ' ' + str(lag):>12}  insufficient data")
            continue
        fits.append((f"{label} lag {lag}", r))
        cell = lambda e: f"{e['beta']:+.3f} [{e['lo']:+.3f}, {e['hi']:+.3f}] p={e['p']:.2f}"  # noqa: E731
        print(f"{label + ' lag ' + str(lag):>12}{r['periods']:>8}  {cell(r['treatment']):>26}  "
              f"{cell(r['placebo']):>26}  {cell(r['difference']):>28}  {r['treatment']['mde']:>9.3f}")

    print()
    for key, claim in (("treatment", "bond buyers lead their peers"),
                       ("difference", "bond buyers lead peers by more than size-matched non-buyers")):
        p_raw = [r[key]["p"] for _, r in fits]
        reject, p_holm, _, _ = multipletests(p_raw, alpha=ALPHA, method="holm")
        hits = [(name, ph) for (name, r), rej, ph in zip(fits, reject, p_holm) if rej and r[key]["beta"] > 0]
        verdict = "YES" if hits else "no evidence"
        detail = ", ".join(f"{n} (Holm p={p:.3f})" for n, p in hits) if hits else \
            f"smallest Holm-adjusted p = {min(p_holm):.3f}"
        print(f"  {claim}: {verdict}; {detail}")
    best = min(fits, key=lambda f: f[1]["treatment"]["mde"])
    print(f"  smallest detectable treatment coefficient (80% power): {best[1]['treatment']['mde']:.3f} ({best[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
