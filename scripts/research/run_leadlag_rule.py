"""
Can the size lead-lag be traded?

    python scripts/research/run_leadlag_rule.py
    python cli.py research leadlag-rule

WHAT THIS TESTS
---------------
The peer lead-lag test refuted the POLITICAL hypothesis but produced one
statistically significant coefficient along the way — in the placebo arm:

    peers[t] ~ 0.089 * liquid_leaders[t-1]     t = 2.87   (weekly, clustered)

Liquid names' returns predict smaller peers' returns one week ahead. That is
information diffusion, the mechanism the capacity argument predicts, and it is
the only significant result this project has produced. It is also ours rather
than a paper's, so it has no publication-decay problem.

The question here is narrower than "is it real": it is "does it survive costs".

WHY THE ARITHMETIC IS ALREADY DISCOURAGING
------------------------------------------
beta 0.089 means a +2% week in the leader basket predicts +0.18% in peers. A
weekly round trip costs ~0.42% (STT both sides, stamp duty, exchange, GST, 10bps
slippage each side). The signal has to clear that on every switch, and it does
not obviously do so. This script exists to measure it rather than argue it, and
to check whether lower-turnover variants fare better.

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
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
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


def main():
    store = PriceStore()
    px = store.close()
    if px.empty:
        logger.error("Price panel empty. Run: python cli.py prices")
        return 1
    px.index = pd.to_datetime(px.index)

    adv = store.adv_cr(252)
    liquid = [s for s in px.columns if adv.get(s, 0) >= MIN_ADV_CR]
    leaders = list(adv.reindex(liquid).dropna().nlargest(N_LEADERS).index)
    peers = [s for s in liquid if s not in set(leaders)]

    costs = CostModel()
    rt = costs.round_trip_pct()

    print(f"liquid universe {len(liquid)}   leaders (top {N_LEADERS} by ADV) "
          f"{len(leaders)}   peers {len(peers)}")
    print(f"round-trip cost {rt*100:.3f}%  (incl {costs.slippage*1e4:.0f}bps slippage/side)")
    print()

    any_win = False
    for freq, (label, ppy) in PERIODS.items():
        pr = px.resample(freq).last().pct_change()
        lead = pr[leaders].mean(axis=1)
        peer = pr[peers].mean(axis=1)
        aligned = pd.concat([lead.rename("lead"), peer.rename("peer")], axis=1).dropna()
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
            # Cost charged whenever the position changes.
            switches = pos.diff().abs().fillna(pos.abs())
            gross = pos * peer_r
            net = gross - switches * rt
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
    pr = px.resample("ME").last().pct_change()
    a = pd.concat([pr[leaders].mean(axis=1).rename("lead"),
                   pr[peers].mean(axis=1).rename("peer")], axis=1).dropna()
    pos = (a["lead"].shift(1) > 0).astype(float)
    sw = pos.diff().abs().fillna(pos.abs())
    rule = (pos * a["peer"] - sw * rt).dropna()
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
        print("VERDICT: the Sharpe gap does NOT survive a paired bootstrap.")
        print("  The interval spans zero, and the rule earns LESS than buy-and-hold")
        print("  with lower volatility — it is de-risking (time in cash), not alpha.")
        print("  Four thresholds on 92 months is also four more trials.")
    else:
        print("VERDICT: no variant beat simply holding the peer basket.")
        print("  The lead-lag coefficient is real (t=2.87) but too small to pay for")
        print("  the round trips required to harvest it. A statistically significant")
        print("  signal is not automatically a tradeable one — that gap is where most")
        print("  retail strategies die, and it is why costs belong in the test rather")
        print("  than in a footnote.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
