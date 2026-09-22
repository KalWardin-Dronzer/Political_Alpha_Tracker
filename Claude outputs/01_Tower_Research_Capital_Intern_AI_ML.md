# VIVEK KUMAR
+91-7870145339 | vivek.kumar240043@gmail.com | linkedin.com/in/vivek-kumar | github.com/KalWardin-Dronzer

> **Target:** Intern – AI/ML, Tower Research Capital (Gurgaon) · **CV family:** `QR` · **Match score: 95**

---

Quantitative Economics & Data Science student with published research in distribution-free uncertainty quantification for option pricing. Experience building and validating systematic signal-generation pipelines end to end — factor construction, walk-forward backtesting, out-of-sample validation and Kelly-based position sizing — in Python.

## RESEARCH & PUBLICATIONS

**Vivek Kumar**, Dr. Mrinal Jana. *"Distribution-free Uncertainty Quantification for Option Pricing Using Residual-space Conformal Prediction."* **CIMA 2026, Accepted.** Proceedings to appear in Springer LNNS (Paper ID-498, Scopus-indexed).
- Developed a novel distribution-free framework for quantifying prediction uncertainty, directly applicable to risk quantification in forecasting where parametric assumptions fail.

## EDUCATION

**Birla Institute of Technology, Mesra** — Integrated M.Sc. in Quantitative Economics and Data Science `2022 – 2027`
Coursework: Econometrics, Time Series Econometrics, Resampling Techniques & Statistical Computation, Statistical Machine Learning, Algorithms for Big Data

## QUANTITATIVE PROJECTS

**Systematic Alpha Research & Backtesting Pipeline** — `Python, XGBoost, NetworkX, PostgreSQL, Docker, AWS EC2`
- Developed a multi-factor predictive scoring model combining graph-based features, statistical signals and NLP-extracted variables; validated via walk-forward backtesting, achieving **66.7% out-of-sample accuracy** as the core model-performance KPI.
- Trained a heavily regularised **XGBoost** model under **walk-forward chronological cross-validation** to optimise signal weights and prevent overfitting; identified pre-event volume z-score as the top predictive feature.
- Validated the strategy against a blind 2024–2025 out-of-sample window, achieving an **81.8% win rate** across high-conviction predicted events (9 of 11).
- Implemented **Fractional (Half-) Kelly Criterion** position sizing with a hard 5% per-trade portfolio cap to enforce mathematical risk management against tail losses.
- Ran base-rate significance testing against control groups and measured post-event return spreads at 30/60/90/180/360-day horizons to validate the hypothesis statistically rather than anecdotally.
- Designed and deployed a fully automated ETL pipeline ingesting 5+ heterogeneous live sources daily with validation and quality checks across 126+ tracked entities; operationalised with Docker, CI/CD and AWS EC2, backed by a pytest suite across 10+ test modules.

**Regime-Aware Genetic Algorithm for Portfolio Optimization** — `Python, SciPy, Pandas, NumPy`
- Engineered a regime-aware genetic algorithm **from scratch** for multi-asset portfolio optimization across a 26-asset global universe.
- Integrated dynamic volatility-based leverage scaling and turnover-aware fitness constraints, achieving a **1.23 Sharpe Ratio** with maximum drawdown limited to **−18.5%**.

**Bayesian Inference for Epidemiological Modeling** — `R, Probabilistic Programming`
- Applied adaptive **Metropolis-Hastings MCMC** (40,000 iterations) for Bayesian inference on real-world transmission data, estimating R₀ = 2.72 and a 5.75-day infectious period.
- Evaluated model convergence and posterior uncertainty using trace diagnostics, acceptance-rate tuning (18.1%) and sensitivity analysis; documented all assumptions and limitations.

## TECHNICAL SKILLS

**Languages:** Python, R, SQL
**Quantitative Methods:** Backtesting, Walk-Forward Validation, Out-of-Sample Testing, Factor Models, Portfolio Optimization, Monte Carlo, Kelly Criterion, Option Pricing
**Statistics:** Bayesian Inference, MCMC, Uncertainty Quantification, Conformal Prediction, Hypothesis Testing, Time Series, Stationarity, Regression
**ML:** Scikit-learn, XGBoost, Cross-Validation, Regularization, Overfitting Control
**Tools:** Pandas, NumPy, SciPy, statsmodels, Git, Docker, Linux, pytest

## ACHIEVEMENTS

**Neurohack, IIT Guwahati — 26th nationally.** Architected a scalable long-term memory system for LLMs handling 1,000+ conversation turns; hybrid semantic + BM25 retrieval at sub-100ms latency.

---
### Tailoring notes — delete before sending
- **Why this scores 95:** Tower is a quant prop firm. Backtesting, Kelly sizing, walk-forward validation and overfitting control are their daily vocabulary, and you have all four on live work rather than a notebook.
- **Publication is at the top on purpose.** It is the rarest thing you have and it is on-domain for a trading firm.
- **Prepare for:** a hard DSA + probability screen before a human reads this. Your `DSA-in-C-` and `DSA-in-Python-` repos should be tidied — they will be looked at.
- **Expect to be asked:** "You have no C++. Why?" Answer with the Python-first systems you have actually shipped, and say you are learning it. Do not bluff.
- **CGPA omitted deliberately** — Tower gates high and 7.05 does not help you here. Include it only if their form demands it.
