# Political Alpha Tracker

> Zero-cost OSINT pipeline for detecting politically-connected government contract winners in the Indian micro-cap/small-cap space.

## What It Does

The system automatically:
1. **Generates a watchlist** of 40-60 micro-cap companies in government-dependent sectors (defence, railways, power, infrastructure)
2. **Monitors BSE announcements** daily for new government contracts won by these companies
3. **Checks fundamental health** (debt-to-equity, operating cash flow, promoter pledging)
4. **Maps board directors** to Electoral Trust/Bond donor networks using MCA DINs
5. **Scores political connections** via a weighted Alpha Query (director exclusivity × path proximity × donation magnitude)
6. **Sends Telegram alerts** when a politically-connected company wins a contract with a score above threshold

## The Alpha Query

The core insight: when a company wins a government contract, AND one of its directors also sits on the board of a known Electoral Trust donor company, the connection suggests asymmetric information flow.

```
ListedCompany ←[SITS_ON_BOARD]→ Director ←[SITS_ON_BOARD]→ DonorCompany →[DONATED_TO]→ ElectoralTrust
```

Scoring formula:
```
alpha_score = 0.4 × exclusivity + 0.3 × proximity + 0.3 × magnitude

exclusivity = 1 / total_board_seats   (fewer seats = stronger signal)
proximity   = 1 / path_length         (fewer hops = stronger)
magnitude   = tiered(donation_amount)  (>₹10Cr=1.0, >₹1Cr=0.7, >₹10L=0.4)
```

## Architecture

```
├── main.py                 # Daily pipeline orchestrator
├── refresh.py              # Quarterly/annual refresh operations
├── requirements.txt
├── .env.example
├── .gitignore
├── data/
│   ├── cache.sqlite        # SQLite cache (auto-generated)
│   ├── graph.json          # NetworkX graph (auto-generated)
│   └── electoral_bonds.csv # SBI disclosure data (you provide)
├── src/
│   ├── config.py           # All constants, thresholds, patterns
│   ├── cache_manager.py    # SQLite caching layer
│   ├── watchlist_generator.py  # 4-stage automated watchlist funnel
│   ├── bse_monitor.py      # BSE announcement scraper
│   ├── financial_screener.py   # Fundamental health checks
│   ├── mca_resolver.py     # MCA director resolution (DIN extraction)
│   ├── entity_resolver.py  # CIN/DIN entity matching + fuzzy fallback
│   ├── donor_ingester.py   # Electoral Trust/Bond data ingestion
│   ├── graph_manager.py    # NetworkX graph + Alpha Query
│   ├── notifier.py         # Telegram alerts + /exit command
│   └── backtest.py         # Statistical validation
├── tests/
│   ├── conftest.py         # Shared fixtures
│   ├── test_cache_manager.py
│   ├── test_entity_resolver.py
│   ├── test_graph_manager.py
│   ├── test_bse_and_utils.py
│   └── test_integration.py
└── .github/workflows/
    ├── daily_tracker.yml       # Mon-Fri 6 PM IST
    ├── weekly_prune.yml        # Sunday
    ├── quarterly_refresh.yml   # 1st of Jan/Apr/Jul/Oct
    └── annual_donor_refresh.yml # March 15
```

## Setup

### 1. Clone and Install

```bash
git clone https://github.com/your-username/political-alpha-tracker.git
cd political-alpha-tracker
pip install -r requirements.txt
```

### 2. Download Electoral Bond Data (One-Time)

Download the SBI Electoral Bond disclosure CSV from the [ECI website](https://www.eci.gov.in) or [Kaggle](https://www.kaggle.com) (search "India Electoral Bonds SBI"). Save it as `data/electoral_bonds.csv`.

Expected columns: `purchaser_name`, `denomination`, `encashment_party`, `purchase_date`

### 3. Set Up Telegram Bot

The system uses a Telegram bot to send you alerts and let you manage positions.

**Part A: Get the Bot Token**
1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)** (the official bot creator).
2. Send the command `/newbot` and follow the prompts to give your bot a name and username.
3. BotFather will give you an **API Token** (a long string like `1234567890:ABCdef_GHI...`). 
4. This is your `TELEGRAM_BOT_TOKEN`. Keep it secret!

**Part B: Get Your Chat ID**
The bot needs to know *who* to send messages to (your personal chat ID).
1. In Telegram, search for your newly created bot's username and open a chat with it.
2. Click **Start** (or send any message like "Hello" to it). *This is required to allow the bot to message you.*
3. Open a web browser and go to this URL (replace `<YOUR_BOT_TOKEN>` with the token from Part A):
   `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. You will see a block of text (JSON). Look for the `"chat"` section and find the `"id"`. It will be a number like `123456789`.
5. This number is your `TELEGRAM_CHAT_ID`.

**Part C: Save the Credentials**
1. Locally: Copy the `.env.example` file to a new file named `.env` and add your values:
   ```env
   TELEGRAM_BOT_TOKEN=1234567890:ABCdef_GHI...
   TELEGRAM_CHAT_ID=123456789
   ```
2. For Automation: Add these same two variables in your GitHub repository under **Settings → Secrets and variables → Actions → New repository secret**.

### 4. Initial Run Sequence

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

### 5. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/your-username/political-alpha-tracker.git
git push -u origin main
```

Then go to **Settings → Secrets → Actions** and add:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The GitHub Actions workflows will handle everything automatically after that.

## Automation Schedule

| Workflow | Schedule | What It Does |
|---|---|---|
| Daily Tracker | Mon-Fri 6 PM IST | Scan BSE → Screen → Alpha Query → Alert |
| Weekly Prune | Sunday | Remove stale tenders and orphan graph nodes |
| Quarterly Refresh | Jan/Apr/Jul/Oct 1 | Regenerate watchlist + MCA directors + graph |
| Annual Donor Refresh | March 15 | Update Electoral Trust/Bond data |

## User Commands

| Command | Description |
|---|---|
| `/exit SCRIPCODE` | Remove a company from held positions (trade closed) |

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_graph_manager.py -v
pytest tests/test_integration.py -v
```

## Backtest Validation

The system includes a 3-test statistical validation framework:

1. **Base Rate Test** — Are random micro-caps also politically connected? (High rate = noisy signal)
2. **Post-Event Returns** — Do connected contract winners outperform non-connected ones?
3. **Win Rate** — What % of historical alerts would have been profitable at 90 days?

```bash
python -c "
from src.cache_manager import CacheManager
from src.backtest import Backtester
bt = Backtester(CacheManager())
report = bt.run_full_backtest()
print(report)
"
```

## Configuration

All tunable parameters are in `src/config.py`:

| Parameter | Default | Description |
|---|---|---|
| `MARKET_CAP_MIN_CR` | 50 | Minimum market cap (₹Cr) |
| `MARKET_CAP_MAX_CR` | 5,000 | Maximum market cap (₹Cr) |
| `MAX_DEBT_TO_EQUITY` | 2.0 | D/E ratio cutoff |
| `ALPHA_SCORE_THRESHOLD` | 0.5 | Minimum score to fire alert |
| `MAX_PATH_HOPS` | 3 | Max graph traversal depth |
| `HELD_POSITION_EXPIRY_DAYS` | 180 | Auto-expiry for held positions |
| `MIN_CONTRACT_FREQUENCY` | 2 | Min contracts in lookback for watchlist |

## Data Sources

| Source | Type | Frequency |
|---|---|---|
| BSE India API | Corporate announcements | Daily |
| NSE Archives | Industry classification | Quarterly |
| Yahoo Finance (yfinance) | Market cap, D/E, OCF | As needed |
| MCA V3 Portal | Director DINs | Quarterly + on board change |
| data.gov.in | MCA fallback | As needed |
| ECI / MyNeta / ADR PDFs | Electoral Trust donors | Annual |
| SBI Disclosure | Electoral Bond data | One-time (scheme dead) |

## Tech Stack

- **Python 3.11+** — core language
- **NetworkX** — in-memory graph (serialized to JSON)
- **SQLite** — persistent cache via WAL mode
- **Pandas** — data processing
- **RapidFuzz** — fuzzy entity matching
- **yfinance** — market data
- **GitHub Actions** — orchestration (CRON jobs)
- **Telegram Bot API** — alerts & position management

**Zero paid APIs. Zero cloud services. Runs entirely on GitHub Actions free tier.**

## Disclaimer

This tool is for research and educational purposes only. It does not constitute financial advice. Always do your own due diligence before making investment decisions. The creators are not responsible for any financial losses incurred from using this tool.
