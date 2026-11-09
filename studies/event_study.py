"""
Event study: did bond buyers' share prices move when their purchases became known?

    python cli.py study event-study

The design is in src/research/event_study.py: matched buyer-minus-control
portfolio, estimation window of trading days -250 to -11, standard errors from
the portfolio's own variance.

DECISION RULES (declared 2026-11-09, before the study was run)
--------------------------------------------------------------
- Primary test: the names event (published after the close on 14 March 2024),
  CAR over days [0,+1], group-level definition of a connected company. A
  two-sided p below 0.05 counts as a reaction.
- The verdict and parties events at [0,+1] are reported with a Holm correction
  across the three events.
- The [0,+5] and pre-event [-5,-1] windows, the entity-level definition and the
  market-adjusted portfolio are reported as checks and descriptions.
"""

import logging
import sys

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from statsmodels.stats.multitest import multipletests

from src.connections import connections
from src.data.companies import load_companies
from src.data.price_store import PriceStore
from src.research.event_study import EVENTS, PRIMARY_EVENT, PRIMARY_WINDOW, EventStudy

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("event_study")

ALPHA = 0.05


def table(result: dict) -> None:
    res = result["results"]
    print(f"{'event':>9} {'window':>8} {'CAR':>8} {'95% interval':>20} {'p':>6} {'MDE':>7}")
    for _, r in res.iterrows():
        print(f"{r['event']:>9} {r['window']:>8} {100 * r['car']:>+7.2f}% "
              f"[{100 * r['lo']:>+6.2f}%, {100 * r['hi']:>+6.2f}%] {r['p']:>6.3f} {100 * r['mde']:>6.2f}%")


def run(store, companies, level: str, market_adjusted: bool = False) -> dict:
    table_ = connections(level=level)
    connected = set(table_.index[table_["connected"]])
    study = EventStudy(store.close(), store.volume(), companies, connected)
    return study.run(market_adjusted=market_adjusted)


def main():
    store = PriceStore()
    if store.close().empty:
        logger.error("Price panel empty. Run: python cli.py prices")
        return 1
    companies = load_companies()
    print("Events (day 0 = first trading session that could react):")
    for e in EVENTS:
        print(f"  {e.key:>8}  {e.day0}  {e.label}")
    print()

    primary = run(store, companies, "group")
    print(f"=== GROUP LEVEL, matched controls (primary): {primary['n_pairs']} buyer-control pairs; "
          f"estimation window {primary['estimation_days']} days, daily sd of the difference "
          f"{100 * primary['sigma']:.2f}%")
    table(primary)

    res = primary["results"]
    main_rows = res[res["window"] == PRIMARY_WINDOW].set_index("event")
    _, p_holm, _, _ = multipletests(main_rows["p"].values, alpha=ALPHA, method="holm")
    holm = dict(zip(main_rows.index, p_holm))
    p = main_rows.loc[PRIMARY_EVENT]
    print()
    print(f"  primary test ({PRIMARY_EVENT}, {PRIMARY_WINDOW}): CAR {100 * p['car']:+.2f}%, p = {p['p']:.3f} -> "
          f"{'a reaction' if p['p'] < ALPHA else 'no detectable reaction'}; the test could detect "
          f"{100 * p['mde']:.2f}% with 80% power")
    print("  Holm-adjusted p across the three events at " + PRIMARY_WINDOW + ": " +
          ", ".join(f"{k} {v:.3f}" for k, v in holm.items()))

    for label, level, market in (("ENTITY LEVEL, matched controls (check)", "entity", False),
                                 ("GROUP LEVEL, market-adjusted (check)", "group", True)):
        r = run(store, companies, level, market)
        print()
        print(f"=== {label}: {r['n_buyers']} buyers, {r['n_controls']} controls")
        table(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
