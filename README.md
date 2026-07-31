# Political Alpha Tracker - Institutional Quant Edition

> An institutional-grade algorithmic pipeline that tracks political money, detects insider accumulation, and front-runs corporate announcements using alternative data.

## 🚀 The System Architecture (V1 ➡️ V3 Evolution)

This pipeline has evolved from a simple OSINT screener into a highly sophisticated quantitative trading system. It operates across multiple phases:

### Phase 1: The Core Alpha Engine (V1)
1. **Automated Watchlist Generation**: Autonomously discovers 40-60 micro-cap companies in government-dependent sectors (defence, railways, power, infrastructure).
2. **Fundamental Screening**: Auto-rejects companies with dangerous Debt-to-Equity, poor operating cash flow, or heavy promoter pledging.
3. **Political Graph Mapping**: Maps board directors to Electoral Trust/Bond donor networks using MCA DINs (Director Identification Numbers).
4. **The Alpha Query**: Scores connections mathematically (`exclusivity × path proximity × donation magnitude`).

### Phase 2: Insider Intelligence & Pair Trading (V2)
1. **Cluster Buy Detection**: Tracks open-market SAST/PIT disclosures. Triggers an `ULTIMATE INSIDER SIGNAL` if multiple distinct directors/promoters aggressively accumulate shares right before a contract is awarded.
2. **Election Cycle Multipliers**: Applies a `1.5x` alpha boost if the donor's political party is facing an election within 12 months in the contract's issuing state.
3. **Market-Neutral Pair Trading**: Uses an LLM to identify unconnected, fundamentally inferior competitors in the same sector. Suggests a pair trade: *Long the connected winner, Short the unconnected loser.*

### Phase 3: Alternative Data & ML Optimization (V3)
1. **L1 Front-Running (Alternative Data)**: Bypasses the delayed BSE Corporate Announcements by continuously polling government procurement portals (`eprocure.gov.in`). Detects when a watchlist company becomes the Lowest (L1) bidder *weeks* before the official PR.
2. **XGBoost Parameter Optimization**: Uses Walk-Forward Chronological Cross-Validation to train a heavily regularized XGBoost model. Mathematically optimizes the weights of Materiality, Volume Z-Scores, and Alpha Scores to prevent quant overfitting.
3. **Dynamic Position Sizing**: Enforces mathematical risk management using the **Fractional Kelly Criterion** (Half-Kelly). Calculates exactly how much portfolio capital to allocate per trade, capped at a hard 5% maximum to protect against "fat tail" ruins.
4. **Cloud Infrastructure**: Fully Dockerized with PostgreSQL for 24/7 institutional deployment on AWS/GCP, routing through rotating residential proxies.

---

## 🏗️ Project Structure

```text
├── main.py                 # Daily pipeline orchestrator
├── refresh.py              # Quarterly/annual refresh operations
├── requirements.txt
├── docker-compose.yml      # Cloud infrastructure (PostgreSQL + Tracker)
├── Dockerfile              # Docker container build script
├── .env.example
├── data/
│   ├── cache.sqlite        # Local SQLite cache
│   ├── graph.json          # NetworkX graph
│   └── electoral_bonds.csv # SBI disclosure data
├── src/
│   ├── config.py           # All constants, thresholds, patterns
│   ├── cache_manager.py    # Database caching layer
│   ├── watchlist_generator.py  # 4-stage automated watchlist funnel
│   ├── bse_monitor.py      # BSE announcement scraper
│   ├── eprocure_monitor.py # L1 Alternative Data Front-Running
│   ├── insider_tracker.py  # SAST/PIT Cluster Buy Detection
│   ├── financial_screener.py   # Fundamental health checks
│   ├── mca_resolver.py     # MCA director resolution (DIN extraction)
│   ├── donor_ingester.py   # Electoral Trust/Bond data ingestion
│   ├── graph_manager.py    # NetworkX graph + Alpha Query
│   ├── portfolio_manager.py# Kelly Criterion Position Sizing
│   ├── notifier.py         # Telegram alerts
│   └── backtest.py         # ML Walk-Forward Optimization & Testing
└── tests/                  # Pytest test suite
```

---

## 🛠️ Setup & Deployment

You can run this locally on your laptop (SQLite) or deploy it to the cloud for 24/7 execution (Docker + PostgreSQL).

### Method A: Cloud Deployment (Recommended)
1. Rent an Ubuntu VM on AWS EC2 or DigitalOcean.
2. Clone this repository to the server.
3. Configure your `.env` file (Telegram Bot Token, DB Password).
4. Run `sudo docker compose up -d`.
*For detailed instructions, see the `deployment_guide.md` in the project files.*

### Method B: Local Execution
```bash
git clone https://github.com/your-username/political-alpha-tracker.git
cd political-alpha-tracker
python -m venv .venv
source .venv/bin/activate  # (On Windows: .venv\Scripts\activate)
pip install -r requirements.txt
```

### Initial Run Sequence
```bash
# Step 1: Generate watchlist (takes ~15-30 min)
python refresh.py --mode quarterly

# Step 2: Load donor data
python refresh.py --mode annual

# Step 3: Test in dry-run mode (no alerts sent)
python main.py --dry-run

# Step 4: Run live
python main.py
```

---

## 🤖 Telegram Bot Integration

The system communicates entirely through a secure Telegram Bot.
1. Talk to `@BotFather` on Telegram to create a bot and get a `TELEGRAM_BOT_TOKEN`.
2. Get your personal `TELEGRAM_CHAT_ID`.
3. Add these to your `.env` file.

**Bot Features:**
- `🔥 ULTIMATE INSIDER SIGNAL DETECTED 🔥` (Cluster Buy Warnings)
- `🎯 Recommended Position Sizing` (Kelly Allocation)
- `/exit SCRIPCODE` (User command to clear a position)

---

## 📊 Rigorous Backtesting

We do not trust rules blindly. Validate the pipeline mathematically:

```bash
python -c "
from src.cache_manager import CacheManager
from src.backtest import Backtester
bt = Backtester(CacheManager())
bt.run_full_backtest()
"
```

The backtester executes:
1. **Base Rate Check**: Proves that politically connected companies win contracts at statistically significant higher rates than control groups.
2. **Pair Trading Spread Validation**: Calculates post-event returns vs unconnected competitors (30, 60, 90, 180, 360 days).
3. **Election Boost Verification**: Proves whether impending elections actually increase the win rate.
4. **XGBoost ML Optimization**: Uses Walk-Forward chronological cross-validation to discover optimal parameter weights.

---

## ⚙️ Configuration (`src/config.py`)

| Parameter | Default | Description |
|---|---|---|
| `MARKET_CAP_MIN_CR` | 50 | Minimum market cap (₹Cr) |
| `MAX_DEBT_TO_EQUITY` | 2.0 | D/E ratio cutoff |
| `ALPHA_SCORE_THRESHOLD` | 0.5 | Minimum score to fire alert |
| `MAX_POSITION_CAP_PCT` | 5.0 | Absolute max portfolio allocation per trade (Kelly Safety) |
| `KELLY_FRACTION` | 0.5 | Uses Half-Kelly to prevent fat-tail ruin |

---

## Disclaimer
This tool is for research and educational purposes only. It does not constitute financial advice. Always do your own due diligence before making investment decisions. The creators are not responsible for any financial losses incurred from using this tool.
