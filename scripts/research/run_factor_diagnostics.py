"""
Phase 2 diagnostics — is the factor model earning its complexity?

    python run_factor_diagnostics.py

Two questions, both raised by the Phase 2 grid:

1. CONTROL: does picking names by factor score beat picking them at RANDOM
   from the same eligible universe? The grid showed the factor strategy adding
   only +0.057 Sharpe over equal-weighting the universe, which is close enough
   to zero that the honest next question is whether the model is doing anything
   at all. Random selection is the control that answers it. Several seeds are
   run, because a single random draw is itself a coin flip.

2. SAMPLE: the grid's best configuration only traded from 2022-09 (989 days,
   16 rebalances) because the momentum warm-up consumed the early history.
   The panel reaches back to 2019. A longer window will not make a weak signal
   strong, but it will narrow a confidence interval that ran [0.046, 2.295].

Every run is logged as a trial, controls included — they are draws from the
same search and deflating against a count that excludes them would understate
the multiple-testing problem.
"""

import json
import logging
import math
import sys

import numpy as np

from src.data.price_store import PriceStore
from src.research.factor_backtest import (
    FactorBacktest, TrialLog, bootstrap_sharpe_ci, deflated_sharpe_ratio,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("diagnostics")

TOP_N = 40
REBAL = 63
MIN_ADV = 1.0
RANDOM_SEEDS = [1, 2, 3, 4, 5, 6, 7, 8]


def _row(label, s, extra=""):
    return (f"{label:26s} SR {s['sharpe_net']:>6.3f} | "
            f"net {s['annual_return_net_pct']:>7.2f}% | "
            f"cost {s['cost_drag_annual_pct']:>5.2f}% | "
            f"turn {s['annual_turnover_x']:>5.2f}x | "
            f"maxDD {s['max_drawdown_pct']:>7.2f}% | "
            f"n={s['n_days']:>4}{extra}")


def main():
    store = PriceStore()
    if store.close().empty:
        logger.error("Price panel empty. Run: python build_price_panel.py")
        return 1

    bt = FactorBacktest(store, capital=500_000)
    log = TrialLog()
    print(f"Trials logged before this run: {log.count()}\n")

    # ── Q1: control ────────────────────────────────────────────
    print("=" * 84)
    print("DIAGNOSTIC 1 — does the factor beat random selection from the same universe?")
    print(f"(top_n={TOP_N}, rebalance={REBAL}d, ADV>={MIN_ADV} Cr, from 2021-06)")
    print("=" * 84)

    common = dict(start="2021-06-01", top_n=TOP_N,
                  rebalance_days=REBAL, min_adv_cr=MIN_ADV)

    fac = bt.run(selection="factor", **common)
    print(_row("FACTOR", fac.summary()))

    liq = bt.run(selection="liquidity", **common)
    print(_row("LIQUIDITY-ONLY", liq.summary()))

    rnd_sharpes, rnd_returns = [], []
    for sd in RANDOM_SEEDS:
        r = bt.run(selection="random", seed=sd, **common)
        rnd_sharpes.append(r.summary()["sharpe_net"])
        rnd_returns.append(r.summary()["annual_return_net_pct"])
        print(_row(f"RANDOM seed={sd}", r.summary()))

    rs = np.array(rnd_sharpes)
    print("-" * 84)
    print(f"RANDOM control: Sharpe mean {rs.mean():.3f}, sd {rs.std(ddof=1):.3f}, "
          f"range [{rs.min():.3f}, {rs.max():.3f}]")
    print(f"Annual return  mean {np.mean(rnd_returns):.2f}%")

    fac_sr = fac.summary()["sharpe_net"]
    edge = fac_sr - rs.mean()
    z = edge / rs.std(ddof=1) if rs.std(ddof=1) > 0 else float("nan")
    beats = int((rs >= fac_sr).sum())
    print()
    print(f"Factor Sharpe {fac_sr:.3f} vs random mean {rs.mean():.3f}  ->  edge {edge:+.3f} "
          f"({z:+.2f} SD of the random distribution)")
    print(f"Random draws that matched or beat the factor: {beats}/{len(rs)}")
    if beats > 0 or z < 1.0:
        print("  >> The factor model is NOT clearly distinguishable from random")
        print("     selection within this universe. The return is the universe's,")
        print("     not the signal's.")

    # ── Q2: longer sample ──────────────────────────────────────
    print()
    print("=" * 84)
    print("DIAGNOSTIC 2 — the longest window the panel supports")
    print("=" * 84)

    long = bt.run(selection="factor", start="2019-01-01", top_n=TOP_N,
                  rebalance_days=REBAL, min_adv_cr=MIN_ADV)
    ls = long.summary()
    print(_row("FACTOR (from 2019)", ls))
    print(f"  window: {long.params['start']} .. {long.params['end']}, "
          f"{ls['n_rebalances']} rebalances")

    long_rnd = []
    for sd in RANDOM_SEEDS[:4]:
        r = bt.run(selection="random", seed=sd, start="2019-01-01", top_n=TOP_N,
                   rebalance_days=REBAL, min_adv_cr=MIN_ADV)
        long_rnd.append(r.summary()["sharpe_net"])
        print(_row(f"RANDOM (2019) seed={sd}", r.summary()))
    lr = np.array(long_rnd)
    print(f"  random mean over the same window: {lr.mean():.3f}")
    print(f"  factor edge over random: {ls['sharpe_net'] - lr.mean():+.3f}")

    print("\n--- Bootstrap CI, long window ---")
    ci = bootstrap_sharpe_ci(long.returns, n_boot=1000, block_size=20)
    print(json.dumps(ci, indent=2, default=str))

    n_trials = log.count()
    print(f"\n--- Deflated Sharpe, long window ({n_trials} cumulative trials) ---")
    dsr = deflated_sharpe_ratio(long.returns, n_trials=n_trials)
    print(json.dumps(dsr, indent=2, default=str))

    # ── verdict ────────────────────────────────────────────────
    print()
    print("=" * 84)
    passes_ci = bool(ci.get("excludes_zero"))
    passes_dsr = bool(dsr.get("passes"))
    beats_random = (ls["sharpe_net"] - lr.mean()) > 0.30   # a real, not cosmetic, gap
    print("VERDICT")
    print(f"  bootstrap CI excludes zero .......... {passes_ci}")
    print(f"  deflated Sharpe > 0.95 ............... {passes_dsr}")
    print(f"  beats random selection by >0.30 SR ... {beats_random}")
    print()
    if passes_ci and passes_dsr and beats_random:
        print("  PROCEED to Phase 3.")
    else:
        print("  DO NOT PROCEED with the factor model as the primary signal.")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
