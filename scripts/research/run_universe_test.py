"""
TEST A — Is the small/mid-cap universe premium real?

    python run_universe_test.py

THE QUESTION
------------
Phase 2 found that random 40-name portfolios drawn from the liquidity-screened
universe earned Sharpe 1.39-1.55, against Nifty Midcap 100 at 0.787. If that
gap is real it is a strategy needing no alpha at all: low turnover, held past
12 months for the lower tax rate, nothing to forecast and nothing to overfit.

Three reasons it might be an artifact, each tested here:

  1. BENCHMARK MISMATCH. An equal-weight basket was compared to CAP-WEIGHTED
     indices. Equal weighting is itself a size tilt plus a rebalancing premium,
     so part of the gap is the weighting scheme rather than the universe. Fixed
     by decomposing: equal-weight large/liquid names vs equal-weight the whole
     universe isolates size from weighting.

  2. START-DATE LUCK. The window opened 2020-04, weeks after the COVID bottom.
     Any long-only strategy looks brilliant from there. Fixed by reporting
     every sub-period separately, including pre-COVID and post-COVID alone.

  3. UNIVERSE SELECTION. The 1,588 names came from the watchlist generator's
     fundamental screens applied with TODAY's data, which tilts toward
     companies that look good now. Not fully fixable without point-in-time
     fundamentals, but a premium concentrated in one regime is the signature
     of a selection artifact, so sub-period stability speaks to it.

Costs are applied to the equal-weight basket, because maintaining equal weights
is not free, and the survivorship drag from the delisting registry is
subtracted from every figure.

PRE-DECLARED VERDICT — fixed before seeing results
--------------------------------------------------
PASS requires ALL of:
  a) equal-weight universe beats the cap-weighted midcap index in EVERY
     sub-period tested, not just on average
  b) the excess survives costs and the survivorship adjustment
  c) an INVESTABLE version (40 names, annual rebalance, full costs) still
     beats the index
Anything less is a FAIL, and the honest conclusion is an index fund.
"""

import logging
import math
import sys

import numpy as np
import pandas as pd
import yfinance as yf

# Allow running this file directly (python scripts/research/<name>.py) as well
# as through cli.py. Without this the repo root is not on sys.path and the
# `src` package cannot be imported — a regression introduced when these scripts
# moved out of the repo root.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from src.data.price_store import PriceStore
from src.data.delisting_registry import DelistingRegistry
from src.research.factor_backtest import CostModel, FactorBacktest, TrialLog

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logging.getLogger("yfinance").disabled = True
logger = logging.getLogger("universe_test")

TRADING_DAYS = 252

SUBPERIODS = [
    ("pre-COVID",        "2019-01-01", "2020-02-15"),
    ("COVID crash+rally","2020-02-16", "2021-12-31"),
    ("2022 drawdown",    "2022-01-01", "2022-12-31"),
    ("post-COVID",       "2023-01-01", "2026-09-10"),
    ("FULL",             "2019-01-01", "2026-09-10"),
]

INDICES = {"Nifty Midcap 100": "^NSMIDCP", "Nifty 500": "^CRSLDX", "Nifty 50": "^NSEI"}


def sharpe(r):
    r = r.dropna()
    return float(r.mean() / r.std() * math.sqrt(TRADING_DAYS)) if len(r) > 2 and r.std() else 0.0


def ann(r):
    r = r.dropna()
    return float((1 + r).prod() ** (TRADING_DAYS / len(r)) - 1) if len(r) else 0.0


def mdd(r):
    r = r.dropna()
    if r.empty:
        return 0.0
    c = (1 + r).cumprod()
    return float((c / c.cummax() - 1).min())


def index_returns(ticker, start, end):
    try:
        h = yf.Ticker(ticker).history(start=start, end=end)[["Close"]]
        if h.empty:
            return pd.Series(dtype=float)
        h.index = h.index.tz_localize(None)
        return h["Close"].pct_change().dropna()
    except Exception:
        return pd.Series(dtype=float)


def main():
    store = PriceStore()
    px = store.close()
    if px.empty:
        logger.error("Price panel empty. Run: python build_price_panel.py")
        return 1
    px.index = pd.to_datetime(px.index)

    adv = store.adv_cr(252)
    liquid = [s for s in px.columns if adv.get(s, 0) >= 1.0]
    top100 = list(adv.reindex(liquid).dropna().nlargest(100).index)

    # Survivorship drag, subtracted from every constructed-basket figure.
    reg = DelistingRegistry()
    bias = reg.bias_estimate(len(px.columns), "2019-01-01", "2026-09-10")
    drag_annual = bias.annual_drag_pct
    drag_daily = drag_annual / TRADING_DAYS

    # Equal-weight baskets pay to stay equal-weight. Assume ~1x annual turnover.
    costs = CostModel()
    ew_cost_daily = (1.0 * costs.round_trip_pct()) / TRADING_DAYS

    print("=" * 92)
    print("TEST A — IS THE SMALL/MID-CAP UNIVERSE PREMIUM REAL?")
    print("=" * 92)
    print(f"panel: {px.shape[1]} symbols | liquid (ADV>=1Cr): {len(liquid)} | "
          f"largest-100 subset for the size decomposition")
    print(f"survivorship drag applied: -{drag_annual*100:.3f}%/yr "
          f"({bias.n_failures} failures / {bias.universe_size} reconstructed universe)")
    print(f"equal-weight maintenance cost applied: -{1.0*costs.round_trip_pct()*100:.2f}%/yr")
    print()

    # ── Part 1: sub-period stability + size decomposition ──
    print("-" * 92)
    print("PART 1 — sub-period stability, and equal-weight decomposed by size")
    print("-" * 92)
    print(f"{'period':<20}{'EW universe':>13}{'EW top-100':>12}{'Midcap100':>11}"
          f"{'Nifty500':>10}{'Nifty50':>9}   {'EW-vs-Mid':>9}")
    print(f"{'':20}{'(Sharpe)':>13}{'(Sharpe)':>12}{'(Sharpe)':>11}{'(Sharpe)':>10}{'(Sharpe)':>9}")

    verdict_rows = []
    for name, s, e in SUBPERIODS:
        seg = px.loc[(px.index >= s) & (px.index <= e)]
        if len(seg) < 40:
            continue
        ew_all = seg[liquid].pct_change().mean(axis=1) - ew_cost_daily - drag_daily
        ew_big = seg[top100].pct_change().mean(axis=1) - ew_cost_daily - drag_daily

        idx = {k: index_returns(v, s, e) for k, v in INDICES.items()}
        s_all, s_big = sharpe(ew_all), sharpe(ew_big)
        s_mid = sharpe(idx["Nifty Midcap 100"])
        excess = s_all - s_mid
        verdict_rows.append((name, s_all, s_mid, excess, ann(ew_all), ann(idx["Nifty Midcap 100"])))

        print(f"{name:<20}{s_all:>13.3f}{s_big:>12.3f}{s_mid:>11.3f}"
              f"{sharpe(idx['Nifty 500']):>10.3f}{sharpe(idx['Nifty 50']):>9.3f}   {excess:>+9.3f}")

    print()
    print("annualised returns, same rows:")
    print(f"{'period':<20}{'EW universe':>13}{'Midcap100':>12}{'excess':>10}")
    for name, s_all, s_mid, excess, a_all, a_mid in verdict_rows:
        print(f"{name:<20}{a_all*100:>12.2f}%{a_mid*100:>11.2f}%{(a_all-a_mid)*100:>+9.2f}%")

    # ── Part 2: rolling 3-year windows ──
    print()
    print("-" * 92)
    print("PART 2 — rolling 3-year windows (is the premium ever absent?)")
    print("-" * 92)
    ew_full = px[liquid].pct_change().mean(axis=1) - ew_cost_daily - drag_daily
    mid_full = index_returns("^NSMIDCP", "2019-01-01", "2026-09-10")
    common = ew_full.index.intersection(mid_full.index)
    ew_c, mid_c = ew_full.loc[common], mid_full.loc[common]

    win = 756
    rows = []
    for i in range(0, len(common) - win, 126):
        a, b = ew_c.iloc[i:i + win], mid_c.iloc[i:i + win]
        rows.append((common[i].date(), common[i + win - 1].date(),
                     sharpe(a), sharpe(b), sharpe(a) - sharpe(b)))
    print(f"{'window start':>14}{'window end':>14}{'EW SR':>9}{'Mid SR':>9}{'excess':>9}")
    for st, en, sa, sb, ex in rows:
        print(f"{str(st):>14}{str(en):>14}{sa:>9.3f}{sb:>9.3f}{ex:>+9.3f}")
    neg = sum(1 for *_x, ex in rows if ex <= 0)
    print(f"\nwindows where the universe did NOT beat the midcap index: {neg}/{len(rows)}")

    # ── Part 3: investable version ──
    print()
    print("-" * 92)
    print("PART 3 — INVESTABLE version: 40 names, ANNUAL rebalance, full costs")
    print("-" * 92)
    bt = FactorBacktest(store, capital=500_000)
    inv = []
    for seed in (1, 2, 3, 4, 5):
        try:
            r = bt.run(selection="random", seed=seed, start="2019-01-01",
                       top_n=40, rebalance_days=252, min_adv_cr=1.0, log_trial=True)
        except Exception as ex:
            print(f"  seed {seed} failed: {ex}")
            continue
        sm = r.summary()
        net_sr = sm["sharpe_net"]
        net_ann = sm["annual_return_net_pct"] / 100 - drag_annual
        inv.append((seed, net_sr, net_ann, sm["annual_turnover_x"], sm["max_drawdown_pct"]))
        print(f"  seed {seed}: SR {net_sr:>6.3f} | net ann (after survivorship) "
              f"{net_ann*100:>6.2f}% | turnover {sm['annual_turnover_x']:>4.2f}x | "
              f"maxDD {sm['max_drawdown_pct']:>7.2f}%")

    if inv:
        srs = np.array([x[1] for x in inv])
        anns = np.array([x[2] for x in inv])
        print(f"\n  mean SR {srs.mean():.3f} (sd {srs.std(ddof=1):.3f}) | "
              f"mean net annual {anns.mean()*100:.2f}%")

    # ── Verdict ──
    print()
    print("=" * 92)
    cond_a = all(ex > 0 for *_x, ex in [(r[0], r[3]) for r in verdict_rows]) if verdict_rows else False
    cond_a = all(r[3] > 0 for r in verdict_rows)
    cond_b = neg == 0
    cond_c = bool(inv) and float(np.mean([x[1] for x in inv])) > sharpe(mid_c)
    print("PRE-DECLARED VERDICT")
    print(f"  (a) beats midcap index in EVERY sub-period ......... {cond_a}")
    print(f"  (b) beats it in EVERY rolling 3y window ............ {cond_b}")
    print(f"  (c) investable 40-name annual version beats index .. {cond_c}"
          f"   (index SR {sharpe(mid_c):.3f})")
    print()
    if cond_a and cond_b and cond_c:
        print("  PASS — the universe premium looks real and implementable.")
    else:
        print("  FAIL — the premium is regime-dependent or does not survive")
        print("         implementation. Honest conclusion: an index fund.")
    print("=" * 92)
    print(f"\ntrials logged to date: {TrialLog().count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
