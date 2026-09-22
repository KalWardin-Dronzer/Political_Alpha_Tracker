# VIVEK KUMAR
+91-7870145339 | vivek.kumar240043@gmail.com | linkedin.com/in/vivek-kumar | github.com/KalWardin-Dronzer

> **Target:** Research Sciences Intern, Microsoft (Bengaluru) · **CV family:** `RES` · **Match score: 92**

---

Quantitative Economics & Data Science student with an accepted Scopus-indexed publication in distribution-free uncertainty quantification. Experience spanning Bayesian inference, MCMC, time-series econometrics and deep learning, with emphasis on rigorous validation, convergence diagnostics and reproducibility.

## RESEARCH & PUBLICATIONS

**Vivek Kumar**, Dr. Mrinal Jana. *"Distribution-free Uncertainty Quantification for Option Pricing Using Residual-space Conformal Prediction."* **CIMA 2026, Accepted.** Proceedings to appear in Springer LNNS (Paper ID-498, Scopus-indexed).
- Developed a novel **distribution-free** framework producing calibrated prediction intervals without parametric distributional assumptions, applicable wherever those assumptions fail.
- Worked in **residual space** to decouple the uncertainty estimate from the underlying point predictor, so the method transfers across model families.

## EDUCATION

**Birla Institute of Technology, Mesra** — Integrated M.Sc. in Quantitative Economics and Data Science `2022 – 2027`
Coursework: Resampling Techniques & Statistical Computation, Time Series Econometrics, Statistical Machine Learning II, Multivariate Data Analysis, Algorithms for Big Data

## RESEARCH PROJECTS

**Bayesian Causal Inference for Epidemiological Modeling** — `R (deSolve, coda, ggplot2)`
- Applied adaptive **Metropolis-Hastings MCMC** (40,000 iterations) for Bayesian statistical inference on COVID-19 transmission rates from MoHFW / Johns Hopkins CSSE data, estimating **R₀ = 2.72** and a 5.75-day infectious period.
- Designed a **causal framework** to quantify the effect of non-pharmaceutical interventions on disease spread, moving beyond correlational analysis.
- Evaluated model convergence and posterior uncertainty using **trace diagnostics**, acceptance-rate tuning (18.1%) and **sensitivity analysis**; documented all assumptions, limitations and data-quality considerations.
- Implemented the full SIR compartmental model and inference stack in R, reporting posterior means with 95% credible intervals for every estimated parameter.

**Remaining-Useful-Life Prediction on NASA C-MAPSS** — `Python, Deep Learning, Time-Series Sensor Data`
- Built and benchmarked an RUL prediction model on the NASA C-MAPSS turbofan degradation dataset, comparing test-set performance directly against **published literature results**.
- Engineered sensor-window features from multivariate telemetry and ran **per-engine diagnostic error analysis** to surface failure modes that aggregate metrics masked.

**Time Series Analysis of India's Electricity Generation (2019–2025)** — `R, SARIMA`
- Modelled 7 years of monthly national generation data, testing for stationarity and seasonality and selecting **SARIMA(1,1,1)(0,1,1)₁₂** as the best-fit specification for short-horizon forecasting.
- Diagnosed a strong upward trend with annual seasonality and validated residual assumptions before forecasting.

**Long-Form Memory System for LLMs** — *Neurohack, IIT Guwahati — 26th nationally* — `FastAPI, SQLite, Embeddings`
- Architected a memory system handling **1,000+ conversation turns** without prompt growth or performance degradation.
- Engineered hybrid retrieval combining semantic embeddings with lexical **BM25** ranking, at **sub-100ms** latency; built a reproducible benchmark suite measuring long-range recall and conflict-handling accuracy.

## TECHNICAL SKILLS

**Languages:** Python, R, SQL
**Statistical Methods:** Bayesian Inference, MCMC (Metropolis-Hastings), Uncertainty Quantification, Conformal Prediction, Causal Inference, Resampling, Hypothesis Testing
**Econometrics:** Time Series, SARIMA/ARIMA, Stationarity Testing, Multivariate Analysis, Regression, Forecasting
**ML & Optimization:** Scikit-learn, XGBoost, TensorFlow, Deep Learning, Cross-Validation, Genetic Algorithms, Constrained Optimization, Monte Carlo Simulation
**Tools:** statsmodels, SciPy, deSolve, coda, ggplot2, LaTeX, Git

---
### Tailoring notes — delete before sending
- **The publication carries this application.** It is first on the page for that reason. Everything else is supporting evidence that you work at research pace.
- **This is the CV where C-MAPSS and SARIMA earn their place** — they show range across deep learning and classical econometrics, which a research req rewards and a product req does not.
- **Before sending:** confirm the C-MAPSS model architecture wording against your ED407 report. Do not describe an architecture you cannot defend.
- **Known gap:** you list TensorFlow; research teams default to **PyTorch**. If you can get a small PyTorch project up before applying, do it — otherwise be ready to say you have not used it yet.
- **Realistic read:** Microsoft weights this intake heavily toward PhD candidates. The paper is what buys you a read; a referral is what gets you an interview. Try to find a BIT Mesra alum at MSR India first.
