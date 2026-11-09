"""
Can the size lead-lag be traded?

    python cli.py study leadlag-rule

WHAT THIS TESTS
---------------
Large, liquid stocks' returns lead small stocks' returns (Lo and MacKinlay,
1990): news reaches the most traded names first. The political lead-lag test
controls for this with a size-matched placebo arm. This study asks the
practical question about the size effect itself: does holding the smaller
stocks only after the most liquid ones rose beat simply holding them, after
costs?

Leaders are the N_LEADERS names with the highest traded value over the previous
year and peers are every other name above MIN_ADV_CR, both re-formed at the
start of each period from sessions before it. An earlier version picked them by
traded value over the panel's last year, which chose stocks by how they turned
out.

WHY THE ARITHMETIC IS DISCOURAGING
----------------------------------
A weekly round trip costs ~0.42% (STT both sides, stamp duty, exchange, GST,
10bps slippage each side). A lead-lag coefficient of 0.08 means a +2% week in
the leader basket predicts +0.16% in peers, so the signal has to clear the cost
on every round trip. This script measures that rather than argues it, and checks
whether lower-turnover variants fare better.

THE BENCHMARK THAT MATTERS
--------------------------
Not zero, and not an index: BUY-AND-HOLD THE SAME PEER BASKET. A timing rule
justifies itself only by beating the thing it is timing. Anything else flatters
the rule with the basket's own drift.
"""

import logging
import math
import sys

# Allow running directly as well as through cli.py.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd

from src.data.price_store import PriceStore
from src.research.factor_backtest import CostModel, bootstrap_sharpe_ci

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("leadlag_rule")

PERIODS = {"W-FRI": ("weekly", 52), "ME": ("monthly", 12)}
N_LEADERS = 100          # most liquid names = the "leaders"
MIN_ADV_CR = 1.0
# Signal thresholds: trade only when the leader move exceeds this, so a weak
# signal does not buy a round trip it cannot pay for.
THRESHOLDS = [0.0, 0.005, 0.01, 0.02]


def stats(r, ppy):
    r = r.dropna()
    if len(r) < 8 or r.std() == 0:
        return {"sharpe": 0.0, "ann": 0.0, "mdd": 0.0, "n": len(r)}
    curve = (1 + r).cumprod()
    return {
        "sharpe": float(r.mean() / r.std() * math.sqrt(ppy)),
        "ann": float(curve.iloc[-1] ** (ppy / len(r)) - 1),
        "mdd": float((curve / curve.cummax() - 1).min()),
        "n": len(r),
    }


def trading_costs(pos: pd.Series, costs: CostModel) -> pd.Series:
    """Cost per period of a long-or-cash position: the buy side when the rule
    enters, the sell side when it exits. A full round trip pays
    round_trip_pct() once. (An earlier version charged the full round trip on
    every entry AND every exit, doubling the cost.)"""
    change = pos.diff().fillna(pos)
    return (change > 0) * costs.buy_pct() + (change < 0) * costs.sell_pct()


def basket_groups(known: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Leader and peer membership for each period from the traded value known
    at its start: leaders are the N_LEADERS highest, peers the rest above
    MIN_ADV_CR."""
    liquid = known >= MIN_ADV_CR
    leaders = known.where(liquid).rank(axis=1, ascending=False, method="first") <= N_LEADERS
    return leaders, liquid & ~leaders


def basket_returns(store, freq: str) -> pd.DataFrame:
    """Per-period returns of the leader and peer baskets, equal weighted, with
    the number of names in each; membership is re-formed at the start of every
    period from sessions before it."""
    px = store.close()
    px.index = pd.to_datetime(px.index)
    pr = px.resample(freq).last().pct_change(fill_method=None)
    # Traded value over the year to the end of the previous period.
    known = (store.adv_history(252).resample(freq).last().shift(1)
             .reindex(index=pr.index, columns=pr.columns))
    leaders, peers = basket_groups(known)
    return pd.concat([pr.where(leaders).mean(axis=1).rename("lead"),
                      pr.where(peers).mean(axis=1).rename("peer"),
                      leaders.sum(axis=1).rename("n_lead"),
                      peers.sum(axis=1).rename("n_peer")], axis=1).dropna()


def weekly_curves(store) -> pd.DataFrame:
    """Weekly returns of the threshold-0 rule gross and net of costs, and of
    buying and holding the same peer basket. Same steps as main(); used for the
    figure in results/figures."""
    aligned = basket_returns(store, "W-FRI")
    pos = (aligned["lead"].shift(1) > 0).astype(float)
    gross = pos * aligned["peer"]
    return pd.DataFrame({
        "gross": gross,
        "net": gross - trading_costs(pos, CostModel()),
        "buy_and_hold": aligned["peer"],
    })


def main():
    store = PriceStore()
    px = store.close()
    if px.empty:
        logger.error("Price panel empty. Run: python cli.py prices")
        return 1
    costs = CostModel()
    rt = costs.round_trip_pct()
    baskets = {freq: basket_returns(store, freq) for freq in PERIODS}
    weekly = baskets["W-FRI"]

    print(f"leaders: the {N_LEADERS} names with the highest traded value over the previous year; "
          f"peers: the other names above Rs {MIN_ADV_CR:g} crore a day")
    print(f"re-formed every period from sessions before it: median {weekly['n_peer'].median():.0f} "
          f"peers a week, from {weekly.index[0].date()}")
    print(f"round-trip cost {rt*100:.3f}%  (incl {costs.slippage*1e4:.0f}bps slippage/side)")
    print()

    any_win = False
    for freq, (label, ppy) in PERIODS.items():
        aligned = baskets[freq]
        if len(aligned) < 30:
            continue
        sig = aligned["lead"].shift(1)          # only past information
        peer_r = aligned["peer"]

        bh = stats(peer_r, ppy)
        print(f"=== {label} ===")
        print(f"  BUY & HOLD peer basket            "
              f"SR {bh['sharpe']:>6.3f}  ann {bh['ann']*100:>7.2f}%  "
              f"maxDD {bh['mdd']*100:>7.2f}%  n={bh['n']}")

        for thr in THRESHOLDS:
            pos = (sig > thr).astype(float)             # long peers, else cash
            switches = pos.diff().abs().fillna(pos.abs())
            gross = pos * peer_r
            net = gross - trading_costs(pos, costs)
            st = stats(net, ppy)
            trades = float(switches.sum())
            exposure = float(pos.mean())
            edge = st["sharpe"] - bh["sharpe"]
            flag = "  <-- beats buy&hold" if edge > 0 else ""
            if edge > 0:
                any_win = True
            print(f"  rule: long when lead[t-1] > {thr*100:>4.1f}%   "
                  f"SR {st['sharpe']:>6.3f}  ann {st['ann']*100:>7.2f}%  "
                  f"maxDD {st['mdd']*100:>7.2f}%  "
                  f"invested {exposure*100:>4.0f}%  switches {trades:>5.0f}  "
                  f"vs B&H {edge:>+6.3f}{flag}")

        # Gross (cost-free) version of the best-exposure rule, to separate
        # "no signal" from "signal eaten by costs".
        pos = (sig > 0).astype(float)
        gross_only = stats(pos * peer_r, ppy)
        print(f"  same rule GROSS of costs          "
              f"SR {gross_only['sharpe']:>6.3f}  ann {gross_only['ann']*100:>7.2f}%"
              f"   <- signal before friction")
        print()

    # A raw Sharpe gap is not a result. Bootstrap the PAIRED difference against
    # buy-and-hold on the same periods, because that is the comparison the rule
    # has to win, and a gap of +0.2 on 92 months is well inside noise.
    print("--- paired bootstrap of the monthly rule vs buy-and-hold ---")
    a = baskets["ME"]
    pos = (a["lead"].shift(1) > 0).astype(float)
    rule = (pos * a["peer"] - trading_costs(pos, costs)).dropna()
    bh = a["peer"].loc[rule.index]

    def _sr(x):
        return x.mean() / x.std() * math.sqrt(12) if x.std() else 0.0

    rng = np.random.default_rng(42)
    n, block, diffs = len(rule), 6, []
    for _ in range(2000):
        idx, pstop = [], 1.0 / block
        while len(idx) < n:
            start = rng.integers(0, n)
            while len(idx) < n:
                idx.append(start % n)
                start += 1
                if rng.random() < pstop:
                    break
        i = np.array(idx[:n])
        diffs.append(_sr(pd.Series(rule.values[i])) - _sr(pd.Series(bh.values[i])))
    d = np.array(diffs)
    lo, hi = np.quantile(d, [0.025, 0.975])
    obs = _sr(rule) - _sr(bh)
    ret_rule = (1 + rule).prod() ** (12 / n) - 1
    ret_bh = (1 + bh).prod() ** (12 / n) - 1
    print(f"  observed Sharpe difference : {obs:+.3f}")
    print(f"  95% CI                     : [{lo:+.3f}, {hi:+.3f}]")
    print(f"  P(difference <= 0)         : {(d <= 0).mean():.3f}")
    print(f"  return  rule {ret_rule:+.2%}  vs  buy&hold {ret_bh:+.2%}")
    print(f"  vol     rule {rule.std()*math.sqrt(12):.2%}  vs  buy&hold "
          f"{bh.std()*math.sqrt(12):.2%}")
    survives = lo > 0 and ret_rule > ret_bh
    print()

    print("=" * 78)
    if survives:
        print("The rule beat buy-and-hold on BOTH Sharpe and return, and the interval")
        print("excludes zero. Re-check the trial count before acting on it.")
    elif any_win:
        if lo > 0:
            print("VERDICT: the monthly rule's Sharpe gap survives the bootstrap, but the")
            print("  rule earns less than buy-and-hold: it is de-risking (time in cash), not alpha.")
        else:
            print("VERDICT: the Sharpe gap does NOT survive a paired bootstrap; the interval")
            print("  spans zero.")
            if ret_rule < ret_bh:
                print("  The rule also earns LESS than buy-and-hold, with lower volatility:")
                print("  it is de-risking (time in cash), not alpha.")
        print(f"  Four thresholds on {n} months is also four more trials.")
    else:
        print("VERDICT: no variant beat simply holding the peer basket.")
        print("  Whatever lead-lag there is does not pay for the round trips needed")
        print("  to harvest it.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
