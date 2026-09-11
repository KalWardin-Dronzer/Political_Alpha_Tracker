"""
Phase 2 — validate the cross-sectional factor strategy honestly.

    python run_factor_validation.py

Runs a PRE-DECLARED grid of configurations, logs every one of them (including
the failures) to data/backtest_trials.jsonl, then evaluates the best result
against that trial count.

The grid is fixed in this file on purpose. Searching interactively until
something looks good, then reporting only the winner, is precisely the
behaviour the deflated Sharpe ratio exists to punish — and DSR cannot correct
for trials that were never written down.

Reported for every configuration:
  * net and gross Sharpe, and the gap between them (what costs took)
  * a stationary block-bootstrap confidence interval on the Sharpe
  * the deflated Sharpe against the cumulative trial count
  * performance against the equal-weight universe, which is the benchmark
    that actually matters: beating it is the entire justification for
    running a strategy instead of just buying the universe
"""

import json
import logging
import sys

from src.data.price_store import PriceStore
from src.research.factor_backtest import (
    FactorBacktest, TrialLog, bootstrap_sharpe_ci,
    deflated_sharpe_ratio, purged_folds,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("validate")

# ── Pre-declared grid. Do not edit between runs to chase a result. ──
GRID = [
    {"top_n": 20, "rebalance_days": 10, "min_adv_cr": 1.0},
    {"top_n": 20, "rebalance_days": 21, "min_adv_cr": 1.0},
    {"top_n": 20, "rebalance_days": 63, "min_adv_cr": 1.0},
    {"top_n": 40, "rebalance_days": 21, "min_adv_cr": 1.0},
    {"top_n": 40, "rebalance_days": 63, "min_adv_cr": 1.0},
    {"top_n": 20, "rebalance_days": 21, "min_adv_cr": 5.0},
    # Momentum-only: isolates whether the fast reversal leg is paying for its
    # turnover, rather than assuming the three-factor blend is right.
    {"top_n": 20, "rebalance_days": 21, "min_adv_cr": 1.0,
     "weights": {"residual_momentum": 1.0, "reversal": 0.0, "low_vol": 0.0}},
    {"top_n": 20, "rebalance_days": 63, "min_adv_cr": 1.0,
     "weights": {"residual_momentum": 1.0, "reversal": 0.0, "low_vol": 0.0}},
]

START = "2021-06-01"
CAPITAL = 500_000


def main():
    store = PriceStore()
    if store.close().empty:
        logger.error("Price panel empty. Run: python build_price_panel.py")
        return 1

    bt = FactorBacktest(store, capital=CAPITAL)
    log = TrialLog()
    print(f"Trials already logged before this run: {log.count()}\n")

    rows, results = [], {}
    for i, cfg in enumerate(GRID, 1):
        label = (f"top{cfg['top_n']}/reb{cfg['rebalance_days']}d"
                 f"/adv{cfg['min_adv_cr']:g}"
                 + ("/mom-only" if cfg.get("weights") else ""))
        try:
            res = bt.run(start=START, log_trial=True, **cfg)
        except Exception as e:
            print(f"[{i}/{len(GRID)}] {label:34s} FAILED: {e}")
            continue

        s = res.summary()
        results[label] = res
        rows.append((label, s))
        print(
            f"[{i}/{len(GRID)}] {label:34s} "
            f"net SR {s['sharpe_net']:>6.3f} | bench SR {s['benchmark_sharpe']:>6.3f} | "
            f"net {s['annual_return_net_pct']:>7.2f}% | cost {s['cost_drag_annual_pct']:>6.2f}% | "
            f"turn {s['annual_turnover_x']:>5.1f}x | maxDD {s['max_drawdown_pct']:>7.2f}%"
        )

    if not rows:
        logger.error("Every configuration failed.")
        return 1

    # "Best" = highest net Sharpe. Selecting on the same data used to evaluate
    # is exactly the bias DSR corrects for below, which is why the trial count
    # matters more than the winner's headline number.
    best_label, best_summary = max(rows, key=lambda r: r[1]["sharpe_net"])
    best = results[best_label]

    print("\n" + "=" * 78)
    print(f"BEST BY NET SHARPE: {best_label}")
    print("=" * 78)
    print(json.dumps(best_summary, indent=2))

    excess = best_summary["sharpe_net"] - best_summary["benchmark_sharpe"]
    print(f"\nSharpe vs equal-weight universe: {excess:+.3f}")
    if excess <= 0:
        print("  >> The strategy does NOT beat simply holding the universe.")
        print("     No amount of parameter search fixes a negative excess here;")
        print("     it is a statement about the signal, not the configuration.")

    print("\n--- Bootstrap CI on net Sharpe (stationary block, BCa) ---")
    ci = bootstrap_sharpe_ci(best.returns, n_boot=1000, block_size=20)
    print(json.dumps(ci, indent=2, default=str))
    if not ci.get("excludes_zero"):
        print("  >> Interval includes zero. The point estimate is not evidence.")

    n_trials = log.count()
    print(f"\n--- Deflated Sharpe (against {n_trials} logged trials) ---")
    dsr = deflated_sharpe_ratio(best.returns, n_trials=n_trials)
    print(json.dumps(dsr, indent=2, default=str))
    if not dsr.get("passes"):
        print("  >> Below the 0.95 bar: not distinguishable from the best of "
              f"{n_trials} noise draws.")

    print("\n--- Purged, embargoed folds (out-of-sample stability) ---")
    folds = purged_folds(best.returns.index, n_folds=5, purge_days=21, embargo_days=21)
    for f in folds:
        seg = best.returns.loc[f["test"]]
        sr = (seg.mean() / seg.std() * (252 ** 0.5)) if seg.std() else 0.0
        print(f"  fold {f['fold']}  {f['test_start']} .. {f['test_end']}  "
              f"n={len(seg):>4}  Sharpe {sr:>7.3f}")
    sharpes = []
    for f in folds:
        seg = best.returns.loc[f["test"]]
        if seg.std():
            sharpes.append(seg.mean() / seg.std() * (252 ** 0.5))
    if sharpes:
        pos = sum(1 for s in sharpes if s > 0)
        print(f"  folds with positive Sharpe: {pos}/{len(sharpes)}")

    print("\n" + "=" * 78)
    verdict = (
        "PROCEED" if (ci.get("excludes_zero") and dsr.get("passes") and excess > 0)
        else "DO NOT PROCEED"
    )
    print(f"PHASE 2 GATE: {verdict}")
    print("  Requires all three: bootstrap CI excludes zero, DSR > 0.95,")
    print("  and net Sharpe above the equal-weight universe.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
