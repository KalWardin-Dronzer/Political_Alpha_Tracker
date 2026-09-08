# Alpha Generation for the Retail Quant: A Complete Pipeline for NSE Markets

*A pipeline built to sit on top of your existing HRP / Ledoit-Wolf / HMM / Half-Kelly portfolio engine — not replace it.*

---

## 0. Framing: what "best" has to mean here

"Best alpha strategy for a retail trader" is underspecified until you fix the constraints, so here they are, made explicit:

| Constraint | What it rules out |
|---|---|
| **Capital** (lakhs, not crores) | Anything needing deep diversification across hundreds of names, or strategies whose edge only shows up at institutional scale |
| **Transaction costs** (STT, exchange fees, GST, stamp duty, DP charges — see §5) | High-turnover strategies; anything with a raw edge under ~20-30 bps per trade |
| **Data access** (no Bloomberg, no L2/L3 book, no point-in-time fundamentals vendor) | Anything needing tick data, order-book microstructure, or expensive alt-data |
| **Latency** (retail co-location doesn't exist) | HFT, market making, anything competing on speed |
| **Regulation** (SEBI's retail algo framework is now fully live — §10) | Undisclosed black-box strategies above the order-rate exemption threshold |

Given those, this document argues for one primary strategy and one optional satellite, then builds out the full pipeline — data, signal, backtest, risk, execution — for the primary one. Throughout, I'll flag where a piece plugs directly into what you've already built (HRP, Ledoit-Wolf shrinkage, HMM regime detection, Half-Kelly sizing, the Political Alpha Tracker's walk-forward harness) versus where it's genuinely new.

---

## 1. The core insight: your portfolio engine is signal-blind

This is the single most important thing in this report, so it goes first.

HRP — with or without Ledoit-Wolf shrinkage — **never looks at expected returns**. It clusters assets by correlation structure and allocates so that riskier branches of the tree get less capital. That's *why* it's stable (no matrix inversion, no sensitivity to noisy return estimates), but it's also why, on its own, it cannot generate alpha. Multiple independent analyses of HRP converge on the same point: it was built specifically because expected returns are so hard to forecast accurately from historical data, which is precisely why it solves only a risk-allocation problem and deliberately leaves return forecasting out entirely — an allocator, not a signal generator, in the words of one practitioner walkthrough of the algorithm. Put more bluntly by another source: risk parity is only ever as good as the return stream you feed it; feed it zero-edge assets and diversifying them better still gets you zero edge.

That's not a knock on your existing project — HRP + Ledoit-Wolf + HMM regime detection + Half-Kelly is a genuinely good **risk-management and portfolio-construction stack**, and 1/N or naïve risk-parity portfolios are hard to beat out-of-sample precisely *because* they don't try to forecast returns. But it means the "alpha generation" the prompt asks for has to come from a layer that sits *upstream* of HRP: a cross-sectional signal that ranks stocks by expected return, which HRP then allocates around instead of ignoring.

This isn't a hand-wavy fix, either — it's an active area of the same literature your HRP work draws on. A April 2026 paper ("Beyond De Prado and Cotton") makes the point directly: HRP and its Schur-complement generalization are described as blind to return signals, since both only ever solve the minimum-variance problem and have no mechanism for accommodating a return forecast — and the paper proposes **HRP-μ**, a hierarchical allocator that accepts an arbitrary return signal μ and collapses back to standard HRP when μ is flat. That is exactly the shape of the extension this report recommends: keep your tree-clustering and Ledoit-Wolf-shrunk covariance for the *risk* side, tilt the recursive-bisection splits by a signal for the *return* side.

**So the actual deliverable of this report is the signal layer** — the piece your pipeline doesn't have yet — plus the execution and compliance machinery to run it live on NSE.

---

## 2. Why not the obvious alternatives

Quick elimination, since "best" only means something relative to what it beat:

- **Pure technical-indicator strategies** (MA crossovers, RSI thresholds, etc.) — thin-to-nonexistent genuine edge once realistic costs are applied; mostly survives in backtests through look-ahead bias or curve-fit parameters. Not a serious candidate for "alpha generation."
- **Intraday / high-frequency approaches** — retail has no co-location, no L2 book, and pays STT + exchange charges + GST on every leg. The cost-per-trade math (§5) makes anything needing hundreds of round-trips a year structurally unprofitable before you even test the signal.
- **Buying options for directional views** — this is where the data is most damning. SEBI's FY26 study of individual F&O traders found **87.7% lost money**, with roughly **92% of those losses concentrated in options** specifically, and about **97% of individual traders were predominantly option *buyers*** (only ~2% were predominantly sellers). That's not a signal-quality problem you can out-model — it's the volatility risk premium working exactly as the academic literature says it should (see §4c): option buyers pay a persistent premium on average. Directional option buying is excluded as a strategy on this evidence alone.
- **Large-cap-only momentum** — real, and documented in Indian markets, but this is also the most crowded, most-covered segment where institutional capital competes hardest. The edge that remains after costs is thin.
- **Complex black-box ML on a short, single history** — with only a handful of years of NSE daily data, the number of model variants you can honestly test before **Deflated Sharpe Ratio** math tells you you're overfitting is small (see §7). A retail researcher iterating quickly in a notebook can blow through that budget in an afternoon without realizing it.

What's left, and what several independent lines of evidence converge on, is a **cross-sectional, EOD-frequency, moderate-turnover equity factor strategy tilted toward the less liquid end of the NSE universe** — which is also, not coincidentally, where retail has a *structural* advantage over institutional quant capital.

---

## 3. Why the small/mid-cap tilt is the actual retail edge, not just a workaround

This deserves its own section because it's the part of "best strategy for a retail trader" that's usually argued backwards — people treat small-cap exposure as a compromise forced by limited capital rather than as the source of edge itself.

The mechanism: institutional quant funds are **capacity-constrained**. As assets under management grow, a strategy's ability to deploy capital without moving the price it's trying to exploit degrades — signal decay, market impact, and crowding all bite harder with scale, which is why top-tier quant funds are increasingly closing to new capital or imposing hard AUM limits specifically to protect the edge that attracted the capital in the first place. A fund managing ₹500 crore *is* the market in a stock that trades ₹5 crore a day; it structurally cannot take a meaningful position without destroying its own edge. A retail account sized in lakhs faces none of that constraint in the same names.

This isn't just theoretical — it shows up directly in the Indian short-term reversal/momentum literature: momentum is strongest and most persistent in the **most liquid** stocks (where institutions compete hardest and crowd the trade out), while short-term reversal is significantly stronger among the **most illiquid** stocks — precisely the segment where retail can operate and large funds structurally cannot. That's a clean, empirically-documented map from "retail capital-size constraint" to "specific factor + specific liquidity tier where that constraint stops being a disadvantage and becomes an advantage."

**Practical implication:** the universe for this strategy should deliberately include NSE mid- and small-cap names (not just Nifty 100/200), with a liquidity *floor* (not ceiling) to stay tradeable — see §5 for the specific screen.

---

## 4. The recommended strategy

### 4a. Primary: cross-sectional multi-factor equity ranking, weekly/bi-weekly rebalance

**What it is:** a composite ranking signal — short-term reversal, intermediate momentum, and a low-volatility/quality tilt — computed cross-sectionally each rebalance over a liquidity-screened NSE mid/small-cap universe, standardized into a single expected-return score μ, which feeds into your existing HRP + Ledoit-Wolf machinery as the "μ" in HRP-μ instead of being ignored. Position sizing comes off a Ledoit-Wolf-regularized multi-asset Kelly, scaled down by a fractional Kelly factor and further shrunk when your HMM flags a stressed regime.

**Why these three factors specifically, not more:**
- *Short-term reversal* (roughly 1-week to 1-month lookback) — strongest precisely in the illiquid tier per §3, and well-documented in India specifically (Griffin et al. find it significant in Indian equities; more recent liquidity-conditioned work confirms it concentrates in low-turnover names).
- *Intermediate momentum* (6–12 month, skip-most-recent-month to avoid overlapping with reversal) — the best-documented cross-sectional anomaly in Indian equities, present in both BSE and NSE studies across multiple decades, strongest in liquid names and during trending regimes (2014–18, 2020–21).
- *Low-volatility / quality tilt* — used less as an independent return driver and more as a **risk modifier**: one of the four well-documented factor return sources (alongside value, momentum, quality) in institutional multi-factor construction, and it dovetails naturally with the "riskier branch gets less capital" logic already baked into HRP's recursive bisection.

Momentum and reversal are close to *orthogonal* signals operating on different horizons and different liquidity tiers — combining them (rather than picking one) is standard practice specifically because single-factor exposure is fragile and multi-factor composites are more robust to any one factor's bad regime.

**Signal combination:** standardize each factor cross-sectionally to a z-score, weight by trailing Information Coefficient / Information Ratio (i.e., factors that have been working recently get more say — recompute this periodically, don't set-and-forget), and cap any single asset's tilt so no name dominates the composite. This is the standard IC-weighted composite approach used in practitioner multi-factor construction, and it maps directly onto the μ vector that HRP-μ consumes.

### 4b. Why *not* pure ML cross-sectional prediction as the primary

Not excluded on principle — gradient-boosted or linear cross-sectional return models are a legitimate next step *once the factor pipeline is validated and you have a longer track record of point-in-time data*. But as the **primary, first** strategy, given the data constraints in §5, the risk is that flexible model search on a handful of years of daily data quietly burns through your effective-trials budget before you've noticed (§7 works this out numerically). Factor-based signals are simpler, more interpretable, have decades of out-of-sample evidence *outside* your own backtest, and are the more defensible place to start. Treat ML-based signal generation as the roadmap item it is in §12, not the launch strategy.

### 4c. Satellite (optional, capped): volatility risk premium harvesting via index options

This is the part of the report that most directly extends your CQR thesis work, so it's worth including even though it's explicitly secondary.

**The evidence:** there's a substantial, decades-deep academic literature on the volatility risk premium — implied volatility systematically exceeds realized volatility on average, and systematic option *selling* (not buying) has been shown to harvest that spread as excess return, both in single-name and index options. It's the same mechanism visible in the SEBI retail data from a different angle: buyers pay the premium, sellers collect it, and only ~2% of Indian retail F&O participants are predominantly sellers.

**Why it's a satellite, not the primary, and why your own thesis work is directly relevant to sizing it responsibly:** the payoff profile of short volatility is sharply non-Gaussian — small, frequent gains and rare, large losses — and academic work on the strategy notes that its apparent risk is understated whenever the backtest sample happens not to include a genuine market crash, since the loss tail simply hasn't shown up yet in that window. An industry commentary makes the same point about track records: a manager who systematically writes options can look consistently profitable and low-risk for years, right up until a single tail event erases all of it at once. This is exactly the kind of miscalibration your thesis is *about*: your CQR work already identified a coverage gap between nominal and empirical intervals that widens specifically under volatility-regime shifts and in OTM moneyness bins — i.e., predictive uncertainty is *understated* in precisely the conditions where a naive option-seller gets hurt. If you build this satellite, use your own stratified conformal calibration to size it: treat the width of the calibrated predictive interval as a confidence signal and shrink the fractional-Kelly allocation as that interval widens, rather than sizing off a flat implied-vs-realized spread. §8 works through a toy version of that scaling.

**Cost reality check that argues for keeping this small:** Budget 2026 raised STT on options premium from 0.10% to 0.15% (effective April 1, 2026) and on futures from 0.02% to 0.05% — confirmed across NSE/exchange circulars and multiple broker disclosures. Combined with the January 2026 lot-size revision (Nifty 50 now 65 units per lot, notional value kept in a defined band by periodic SEBI review) and a mandatory extra Extreme Loss Margin on short index options on expiry day, the frictions on this sleeve are non-trivial and have gone up recently, not down. **Recommendation: cap this sleeve at a small, fixed fraction of total capital (e.g., 10–15%), use defined-risk structures (credit spreads, not naked shorts), and never let it be sized by the same capital pool that's funding margin for the equity sleeve.**

---

## 5. Data acquisition pipeline

### Universe construction
- Base universe: NSE mid-cap + small-cap indices (not just Nifty 100/200) — this is where §3's structural edge lives.
- Liquidity floor, not ceiling: exclude names below a minimum average daily traded value (illiquidity you can't exit is worse than illiquidity that gives you an edge — pick a threshold like ₹1–2 crore ADV and hold it a year before revisiting).
- **Point-in-time constituents, not today's list applied backward.** This matters more than it sounds: survivorship bias from using current index membership on historical backtests has been shown to inflate annualized returns by roughly 1.6 percentage points and Sharpe ratios by as much as 0.5 in controlled comparisons (CRSP US data, 1926–2001; CRSP survivorship-free vs. biased). The effect is worst exactly in the small-cap segment this strategy targets, since that's where delistings, mergers, and failures are most common. Build (or source) a delisted-securities list alongside your active universe.

### Data sources
| Source | Use | Cost |
|---|---|---|
| `jugaad-data` (Python, actively maintained) | Free NSE bhavcopy (equity + F&O), historical EOD | Free |
| `nsefin` / `nseindiapy` (Python) | Bhavcopy, index history, pre-market, FII/DII flows | Free |
| Zerodha Kite Connect (paid tier) | Live + historical candle data once you go live; needed for execution regardless | ₹500/month per API key (current pricing; order placement itself is free via the Personal API tier, which does *not* include market data) |
| `yfinance` | Cross-check / gap-fill, not primary source for NSE-specific corporate actions | Free |

```python
# Illustrative — free EOD bhavcopy pull for backtesting
from datetime import date
from jugaad_data.nse import bhavcopy_save, stock_df

bhavcopy_save(date(2024, 1, 2), "/data/nse/bhavcopy")
df = stock_df(symbol="TATASTEEL", from_date=date(2019, 1, 1),
              to_date=date(2024, 12, 31), series="EQ")
```

### Corporate actions & storage
Adjust for splits/bonuses/dividends before computing any return-based signal — an unadjusted 1-week reversal signal will misfire violently around a bonus issue. At this universe size (a few hundred to ~1,500 names × 10+ years of daily OHLCV), you don't need distributed infrastructure: a local Parquet store or SQLite file is entirely sufficient and keeps the whole pipeline runnable on a laptop, which matters for the "limited capital → limited infra spend" constraint too.

---

## 6. Signal processing / feature engineering

```python
import pandas as pd
import numpy as np

def zscore(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / s.std()

def compute_signals(panel: pd.DataFrame) -> pd.DataFrame:
    """panel: MultiIndex (date, symbol) with adjusted close prices."""
    px = panel['close'].unstack('symbol')

    # Short-term reversal: -1 * trailing 1-week return
    reversal = -px.pct_change(5)

    # Intermediate momentum: 12-month return, skip most recent month
    momentum = px.pct_change(252).shift(21)

    # Low-vol tilt: negative of trailing realized vol (lower vol -> higher score)
    low_vol = -px.pct_change().rolling(63).std()

    # Cross-sectional z-score each factor, each date, THEN combine
    z_rev  = reversal.apply(zscore, axis=1)
    z_mom  = momentum.apply(zscore, axis=1)
    z_lvol = low_vol.apply(zscore, axis=1)

    # IC-weighted composite -- weights re-estimated periodically from
    # trailing realized IC, not fixed forever
    weights = {'reversal': 0.35, 'momentum': 0.45, 'low_vol': 0.20}  # placeholder starting point
    composite = (weights['reversal'] * z_rev
                 + weights['momentum'] * z_mom
                 + weights['low_vol'] * z_lvol)

    # Bound the tilt so no single name dominates HRP-mu's allocation
    return composite.clip(-3, 3)
```

**Point-in-time discipline:** lag every input by at least one trading day relative to when it would actually have been known and tradeable. If a signal's performance collapses when you add a one-day delay, that's usually a sign it was leaking information, not that the delay broke a real effect.

**Feeding this into HRP-μ:** the `composite` matrix above *is* the μ vector — pass it into the signal-tilted recursive bisection instead of a flat/uniform μ, keep the Ledoit-Wolf-shrunk covariance exactly as you have it for the risk side. This is a targeted extension of your existing code, not a rewrite.

---

## 7. Backtesting methodology

### Beyond walk-forward: purging and combinatorial paths
You've already built walk-forward validation for the Political Alpha Tracker (66.7% out-of-sample accuracy) — the upgrade for this pipeline is **Combinatorial Purged Cross-Validation (CPCV)**. Standard walk-forward tests exactly one historical path, so your Sharpe estimate has high variance and no error bars. CPCV partitions the data into N groups, tests combinations of k of them, *purges* training observations whose label windows overlap the test fold, and adds an *embargo* period after each test fold — producing many out-of-sample paths instead of one. A published example: 10 training folds / 8 test folds with a 21-day purge and embargo yields 36 distinct backtest paths from a single dataset. Both `skfolio` and the dedicated `purged-cross-validation` Python package implement this directly (scikit-learn-compatible splitters), so this doesn't need to be built from scratch.

### Deflated Sharpe Ratio — put a number on your own overfitting risk
Every parameter you tune, every factor combination you try, and every lookback window you test is a "trial." With enough trials, you *will* find a combination with an impressive backtested Sharpe ratio out of pure noise — that's the whole point of the Deflated Sharpe Ratio (DSR), which corrects the naive Sharpe for the number of variants searched and for non-normal returns. The rule of thumb from the original paper: with about **5 years of daily data, more than ~45 strategy variants tried pushes the expected best noise Sharpe to roughly 1.0** — meaning a strategy that "beats" 1.0 after 45+ trials might be showing you nothing more than search luck. A rough back-of-envelope calculation confirms the shape of this: on 5 years of daily NSE data, the *expected maximum* Sharpe from pure noise rises from about 1.0 at 10 trials to roughly 1.4 at 100 trials. **Practically: log every variant you test — every factor weight, every lookback, every universe tweak — and compute DSR against that count before trusting a backtested number.** `Wikipedia: Deflated Sharpe ratio` and the original Bailey & López de Prado paper give the formula; several open implementations exist if you'd rather not derive it from scratch.

### Block bootstrap — this is the part that's literally your own coursework
Rather than reporting a single point-estimate Sharpe ratio, resample the strategy's daily return series in contiguous blocks (preserving the serial dependence a naive i.i.d. bootstrap would destroy) and build an empirical confidence interval. This is the **stationary/moving block bootstrap** (Politis & Romano), and the **BCa (bias-corrected and accelerated)** interval you've already studied for non-parametric inference is directly applicable here — it's implemented off-the-shelf in Python's `arch.bootstrap` module:

```python
from arch.bootstrap import StationaryBootstrap
import numpy as np

def sharpe(returns, freq=252):
    return returns.mean() / returns.std() * np.sqrt(freq)

bs = StationaryBootstrap(20, strategy_daily_returns)  # ~20-day mean block length
ci = bs.conf_int(sharpe, 1000, method='bca')
print(f"Sharpe 95% CI: [{ci[0,0]:.2f}, {ci[1,0]:.2f}]")
```

If the lower bound of that interval is at or below zero, the point estimate is not telling you what you think it's telling you — full stop.

### Cost-realistic backtesting (numbers, not hand-waving)
Every one of the above techniques is wasted effort if the backtest ignores costs — a strategy needs to clear roughly **Sharpe 1.0 net of costs to be worth running at all**, with serious quant shops discarding anything under 2. §9 has the precise Indian cost model; make sure it's subtracted from *every* simulated trade, not applied as a single flat haircut at the end.

### What to benchmark against
Equal-weight universe return and the relevant NSE mid/small-cap index, both gross and net of cost, across at least two distinct regimes (e.g., 2020–21 momentum-friendly rally, 2022 drawdown/correction) — a strategy that only works in one regime is a regime bet dressed up as a factor strategy.

---

## 8. Risk management protocols

### Position sizing: uncertainty-scaled fractional Kelly
Full Kelly is a ceiling, never a target — it assumes you know μ and σ exactly, and in practice small errors in the estimated edge produce large errors in position size (with 250 trading days of data, the standard error on an estimated 20%-vol asset's mean return is still roughly ±1.25%, enough to change the "optimal" Kelly size by 2x). Standard practice is half- to quarter-Kelly, and for a multi-asset portfolio, computing raw Kelly off a Ledoit-Wolf-shrunk covariance matrix (which you already have) before applying the fractional scalar.

The extension worth adding, and the one that connects directly to your thesis: scale the Kelly fraction further by a **confidence factor** derived from how wide your signal's predictive uncertainty is — conceptually identical to what a stratified conformal calibration would give you. A wider predictive interval (lower confidence) should mean a smaller bet, independent of the point estimate:

```python
def uncertainty_scaled_kelly(base_fraction, interval_width_pct):
    """base_fraction: e.g. 0.5 for half-Kelly.
       interval_width_pct: width of the (calibrated) predictive interval,
       as a fraction of price. Wider interval -> lower confidence -> smaller size."""
    confidence_scalar = max(0.0, 1 - interval_width_pct)
    return base_fraction * confidence_scalar
```

Illustratively: a 10%-wide interval leaves you at ~45% of full Kelly; a 30%-wide interval (elevated-uncertainty regime) shrinks that to ~35%; a 50%-wide interval — the kind of blow-out your CQR work found specifically around volatility-regime shifts — cuts it to 25%. The exact functional form matters less than the principle: **let realized signal uncertainty, not just the point forecast, drive size.**

### Regime-conditional de-risking
Your HMM is the natural mechanism here — reduce gross exposure, tighten the Kelly fraction further, or widen the liquidity floor when the model flags a high-volatility/stressed regime, rather than running a fixed sizing rule through every market state.

### Portfolio-level caps
- Max weight per name (even after HRP-μ's tilt, no single position should be able to dominate — e.g., cap at 2× the equal-weight level).
- Sector concentration cap.
- The liquidity floor from §5, re-checked at every rebalance, not just at universe construction — a name can go illiquid after you're in it.
- A drawdown circuit breaker at the *strategy* level (e.g., cut gross exposure by half if strategy drawdown exceeds a pre-committed threshold, reviewed rather than reflexively re-levered back up).

### The options satellite's risk rules are separate and stricter
Hard capital cap (§4c), defined-risk structures only, and — critically — never let the same margin pool serve both sleeves, so a bad week in the options sleeve can't force a forced, badly-timed liquidation in the equity sleeve.

---

## 9. Execution logic

### Cost model (current, India, 2026) — the numbers the whole pipeline has to clear
Computed precisely for a standard NSE equity delivery round-trip with a discount broker:

| Component | Rate | Notes |
|---|---|---|
| Brokerage | ₹0 | Zero-brokerage delivery is now standard at discount brokers |
| STT (buy + sell) | 0.1% each side | Unchanged in Budget 2026 |
| Exchange transaction charge | ~0.003% each side | NSE |
| Stamp duty | 0.015% | Buy side only |
| GST | 18% | On brokerage + exchange charge only |
| **Round-trip total (ex-DP)** | **≈ 0.22%** | |
| DP charge | ~₹15–25 flat per scrip per sell-day | **Flat, not proportional** — this is the one that bites small positions hard |

That flat DP charge means cost-as-a-percentage is brutal on undersized positions: a ₹2,000 position pays ~1.0% just in DP charges; a ₹20,000 position pays ~0.10%. **Practical floor: keep individual position sizes above roughly ₹20,000 to keep DP drag under ~0.10% of trade value.** Combined with a 15–25 name universe (a reasonable range for HRP clustering to be meaningful without over-diversifying away the signal), that implies a **practical capital floor of roughly ₹3–6 lakh** to run the equity sleeve sensibly — below that, DP charges alone will erode a meaningful chunk of whatever edge the signal has.

Turnover discipline follows directly from this cost model. Illustratively, at the ~0.22% round-trip rate above:

| Rebalance frequency | Assumed turnover/event | Annualized cost drag |
|---|---|---|
| Daily | 20% | **~11.2%/year** |
| Weekly | 35% | ~4.1%/year |
| Bi-weekly | 35% | ~2.0%/year |
| Monthly | 30% | ~0.8%/year |

Daily rebalancing is not viable at this cost structure for a factor strategy with a realistic (single-digit-percent) annual edge — it eats the entire edge and then some. **Weekly-to-bi-weekly is the sweet spot**: frequent enough to capture the short-term reversal component, infrequent enough that costs stay in the low single digits annually.

### Broker API and order handling
Zerodha Kite Connect (or equivalent — Fyers, Upstox, Angel One SmartAPI all have comparable offerings) at ₹500/month covers historical + live data and free order placement. Use **limit orders with a bounded price band**, not market orders, on anything outside the most liquid names — the small/mid-cap tilt that gives this strategy its edge is exactly the segment where a market order can walk the book. Batch rebalance orders and spread execution across the session rather than firing the whole book at the open.

```python
# Illustrative — compliant order placement (see §10 for why the tag is mandatory)
kite.place_order(
    variety=kite.VARIETY_REGULAR,
    exchange=kite.EXCHANGE_NSE,
    tradingsymbol="TATASTEEL",
    transaction_type=kite.TRANSACTION_TYPE_BUY,
    quantity=qty,
    product=kite.PRODUCT_CNC,          # delivery, not intraday
    order_type=kite.ORDER_TYPE_LIMIT,
    price=limit_price,
    tag="YOUR_REGISTERED_ALGO_ID"      # mandatory under the 2026 framework
)
```

### Before live capital: paper trade
Run the full pipeline against live market data with simulated fills for at least one full rebalance cycle before committing capital — this is where backtest assumptions about slippage and fill quality get tested against reality, cheaply.

---

## 10. Regulatory and compliance notes (India, current as of this report)

SEBI's framework for **"Safer participation of retail investors in Algorithmic trading"** went through a phased rollout across late 2025 and became **fully effective April 1, 2026** — which is now in the past relative to today, so this is live, not upcoming. The shape of it, gathered from broker circulars and compliance guides (verify exact current thresholds against your specific broker's compliance page, since this is a recently-implemented and still-settling framework):

- **Mandatory strategy tagging**: every algo order must carry a unique Strategy/Algo ID assigned during registration with your broker; orders without it are flagged or rejected by the exchange.
- **Static IP whitelisting**: API access is restricted to a small number of pre-registered static IPs — if you're running this from a home connection or rotating cloud IP, you'll need a fixed IP (a small VPS, e.g. AWS `ap-south-1`, is the common solution, and several brokers now prefer India-hosted infrastructure).
- **Broker-as-principal**: your broker takes on formal responsibility for accounts running API-based strategies, which is why the registration step exists at all.
- **A retail exemption band** for low order-rate, self-developed, non-proprietary-black-box strategies exists in most broker interpretations of the framework (commonly discussed around single-digit orders/second) — a weekly-rebalance factor strategy sits nowhere near this threshold, but a "black box" (opaque/complex/AI-driven logic, as opposed to a disclosable rule-based strategy) may face a stricter registration bar depending on how your specific broker classifies it. **Confirm this directly with your broker before going live** — this is exactly the kind of detail that varies by vendor and is still shaking out in practice.
- **Kill switch requirement**: brokers must provide, and your code should support, an immediate full-liquidation/strategy-halt mechanism.

On the F&O side specifically (relevant only if you build the §4c satellite): Nifty 50 lot size is now 65 units (revised January 2026), there is a single weekly expiry structure for benchmark indices, and an additional Extreme Loss Margin applies to short index options on expiry day — all of which raise the effective capital and cost bar for that sleeve versus a couple of years ago.

**Tax note** (not tax advice): F&O trading is treated as business income; equity delivery gains are typically capital gains, though frequency/pattern of trading can shift that characterization. Get this confirmed by an actual CA once you're live — it affects net-of-tax expected returns materially and isn't something to reason about from a blog post.

---

## 11. Honest assessment: where this can still fail

You've been explicit that you want weak points flagged directly, so here they are, without softening:

- **DSR only corrects for disclosed multiple testing.** If you quietly try 200 factor-weight combinations across three notebook sessions and only remember to log the 40 that "looked promising," the DSR calculation on those 40 will still be wrong — it doesn't know about the ones you didn't write down. The discipline of logging *every* trial is doing real work here, not a formality.
- **Factor strategies have long, genuine drawdown periods that are not backtest artifacts.** Momentum in particular carries well-documented "crash" risk — sharp reversals where the most crowded recent winners fall hardest, historically clustering around regime turns (2020 being the canonical recent example). A multi-factor composite dampens but does not eliminate this.
- **The small/mid-cap liquidity edge cuts both ways.** Less analyst coverage means slower price discovery and a genuine edge — but it also means wider spreads, occasional circuit-filter lockups where you simply cannot exit, and noisier, sometimes lower-quality data (stale prints, corporate action errors) that a cleaner large-cap backtest wouldn't expose you to.
- **HRP itself is not guaranteed to beat naive allocation.** A rigorous efficient-implementation study found HRP did *not* outperform simple 1/N allocation out-of-sample on real-world data, even though it delivered materially lower variance. This is a reason to lean on the *signal* layer for the return edge and treat HRP's job as strictly risk control — not a reason to expect HRP itself to be a source of outperformance.
- **This edge is not infinitely scalable, including for you.** The whole thesis in §3 is that retail can operate where institutional capacity can't — but that ceiling is real, just much higher than a single retail account will hit for a long while. It's worth knowing it exists.
- **Most retail failure is behavioral, not technical**, and a good pipeline doesn't immunize you against it. The SEBI numbers (§2, §10) describe a population that mostly wasn't running anything like this pipeline, but the underlying failure mode — abandoning a validated process after a normal, expected drawdown, or quietly increasing size after a lucky run — applies regardless of how rigorous the signal and backtest are.
- **The options satellite is the least defensible part of this report if mis-sized.** Everything in §4c and §8 about uncertainty-scaled sizing is a mitigation, not a guarantee — short volatility strategies have a well-documented history of looking safe for long stretches and then giving back years of gains at once. If in doubt, run the equity sleeve alone first and treat the satellite as a "phase 3" addition, not a launch-day component.

---

## 12. Implementation roadmap

**Phase 1 — Validation (build on free data, no live capital):**
Build the signal pipeline (§6) on free bhavcopy history, run CPCV + DSR + block-bootstrap (§7) across at least two distinct market regimes, and only proceed if the bootstrapped Sharpe confidence interval clears zero with real margin — not just the point estimate.

**Phase 2 — Small live pilot:**
Move to the paid Kite Connect tier, register the strategy under the SEBI framework (§10), paper trade one full rebalance cycle, then deploy a small fraction of intended capital. The explicit goal of this phase is checking whether live slippage and fill quality match what the backtest assumed — if they don't, that's a backtest bug, not bad luck.

**Phase 3 — Scale with discipline, then extend:**
Grow capital only as live-vs-backtest tracking error stays tight. Natural extensions once the core pipeline is validated: the HRP-μ integration itself (§1) if not done from day one; the uncertainty-scaled options satellite (§4c, §8) as a genuinely separate, capped sleeve; and — leaning on the ETL/NLP/graph-feature machinery you already built for the Political Alpha Tracker — alternative or ML-augmented signals as a *complement* to, not a replacement for, the factor core, once you have enough live track record to safely feed a more flexible model without immediately overfitting it.

---

## 13. Sources

- Bailey, D. & López de Prado, M., *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality* (SSRN 2460551); Wikipedia, "Deflated Sharpe ratio"
- López de Prado, M., *Advances in Financial Machine Learning* — purged/embargoed/combinatorial CV; `purged-cross-validation` (eslazarev, GitHub) and `skfolio` Python packages
- Wuebben, B., *Beyond De Prado and Cotton: Hierarchical and Iterative Methods for General Mean-Variance Portfolios* (arXiv 2604.23833) — HRP-μ
- Multiple HRP evaluations on NIFTY 50 and general equity data (arXiv 2202.02728, arXiv 2210.00984; efficient-implementation and real-world analysis papers) — HRP's signal-blindness and mixed record vs. 1/N
- Sensoy & Medhat/Schmeling-referencing NSE/BSE momentum-reversal-liquidity study (ScienceDirect S0927538X23002640); Griffin et al. on short-term reversal in India; NSE-specific momentum/mean-reversion practitioner analysis
- HedgeCo.Net, "Quant Funds Face a Capacity Squeeze"; peaks2tails.com, "Can Retail Traders Compete with Quant Funds?" — capacity constraints and the retail small-cap advantage
- SEBI study coverage (Business Standard, Moneylife, Riddhi Siddhi Share Brokers) — FY22–FY26 individual F&O trader loss statistics
- Guo & Loeper, *The Volatility Risk Premium: An Empirical Study on the S&P 500 Index* (Monash CQFIS); Quantpedia, "Volatility Risk Premium Effect"; Tilgenkamp thesis, *The Volatility Risk Premium Everywhere*
- SEBI/NSE circulars as summarized by Upstox, ICICI Direct, and Kotak Neo announcements — retail algo framework rollout and F&O lot-size/margin changes; multiple broker/tax-advisory summaries of the Budget 2026 STT revision
- Zerodha support documentation and Z-Connect posts — current Kite Connect API pricing and structure
- `jugaad-data`, `nsefin`, `nseindiapy` (PyPI/GitHub) — free NSE data access
- `arch` Python package documentation — bootstrap confidence intervals (stationary bootstrap, BCa)
- Coriva.eu.org and Atlas Peak Research explainers on fractional Kelly and parameter-uncertainty adjustments; Ryan O'Connell Finance, Kelly criterion practitioner notes
- CRSP-based survivorship bias quantification as summarized in LuxAlgo and QuantifiedStrategies backtesting-pitfalls explainers
- Russell Investments, *How to Choose a Strategic Multi-Factor Equity Portfolio*; FactSet Insight, "A Practical Approach to Weighting Signals" — multi-factor combination methodology
- QuantStart, "Sharpe Ratio for Algorithmic Trading Performance Measurement" — realistic Sharpe thresholds

*All figures for costs, regulation, and API pricing reflect the most current information available as of September 2026; verify exact current rates against your broker's contract notes and SEBI/NSE circulars directly before sizing real capital, since several of these (STT, lot sizes, the algo framework) have changed more than once in the past 18 months.*
