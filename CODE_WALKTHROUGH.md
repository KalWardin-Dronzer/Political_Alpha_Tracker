# Deep Dive: Code Implementation Reference

This document is a personal reference guide for the internal mechanics of the Political Alpha Tracker. It breaks down the exact logic, algorithms, and data structures implemented across the core files.

---

## 1. `src/config.py` — The System Brain
This file holds all the tunable hyperparameters and thresholds that govern the system's behavior. 

**Key Sections:**
*   **`THRESHOLDS`**: 
    *   `MIN_CONVICTION_SCORE (4.0)`: The absolute floor. If an event scores below this, the system drops it immediately.
    *   `MAX_VIX (22.0)`: The fear gauge filter. If India VIX > 22, the system halts all new buys to prevent catching falling knives in a market crash.
    *   `MIN_CONTRACT_VALUE_CR (10.0)`: Micro-contracts are ignored to filter noise.
*   **`SCORING_WEIGHTS`**: The weights used in the `alpha_query` math:
    *   `exclusivity (0.4)`: High weight because a director on 50 boards (like a nominee director) provides weak signal compared to a director on 2 boards.
    *   `proximity (0.3)`: How many hops away is the political party?
    *   `magnitude (0.3)`: How big was the donation?
*   **`PAPER_TRADING`**: 
    *   `INITIAL_CAPITAL (100000)`: ₹1 Lakh starting capital.
    *   `KELLY_FRACTION (0.5)`: We use a half-Kelly to prevent blowing up the account during drawdowns.

---

## 2. `src/pipeline_orchestrator.py` — The Main Loop
The `PipelineOrchestrator` acts as the conductor. 

**`run_daily_pipeline(self)`**
This is the master loop executed by `main.py`.
1.  **VIX Check**: It first checks `alpha_engine.fetch_current_vix()`. If VIX > 22, it logs a warning and aborts the buy-side of the pipeline.
2.  **Sell Executions**: It calls `paper_trader.execute_sells()`. **Crucial detail**: Sells are processed *before* buys to free up capital for the day's opportunities.
3.  **Watchlist Scan**: It fetches the active scrip codes from `CacheManager` and passes them to `bse_monitor.scan_watchlist()`.
4.  **Event Processing**: Iterates through every detected event.

**`process_event(self, event)`**
The sequence of evaluation for a single event:
1.  **Filter**: Only processes `contract` or `fund_raising` events.
2.  **Fundamentals**: Calls `financial_screener.check_fundamentals()`. If the company has a negative Operating Cash Flow (OCF) or Debt/Equity > 2.0, it skips.
3.  **Graph Traversal**: Calls `graph_manager.alpha_query(cin)`. If no political link is found in the graph, the base score is 0.
4.  **Conviction Scoring**: Passes the event and graph links to `alpha_engine.calculate_conviction_score()`.
5.  **Technical Adjustment**: Calls `technical_analyzer.analyze()`. If RSI > 70 (Overbought), it deducts points. If RSI < 30 (Oversold), it adds points.
6.  **Execution**: If the final adjusted score > `MIN_CONVICTION_SCORE`, it fires the Telegram alert (`notifier`) and executes the trade (`paper_trader.execute_buy`).

---

## 3. `src/graph_manager.py` — The Knowledge Graph
Built on `networkx`. This is where the "alpha" actually lives.

**`build_graph(self)`**
Rebuilds the graph from the SQLite database.
*   **Nodes**: Adds companies (Listed/Donor), Directors, and Parties.
*   **Edges**: 
    *   `SITS_ON_BOARD`: Links Directors to Companies.
    *   `DONATED_TO`: Links Donors to Parties (with `amount` as a weight).
    *   `RECEIVED_CONTRACT`: Links Listed Companies to Government bodies.

**`alpha_query(self, cin)`**
The core pathfinding algorithm.
1.  Finds all paths from the target `ListedCompany` to any `PoliticalParty` with `cutoff=4` (max 4 hops).
2.  **Path scoring logic**:
    *   *Exclusivity*: Looks at every Director node in the path. `score = 1.0 / nx.degree(G, director)`. A highly connected director dilutes the score.
    *   *Proximity*: `score = 1.0 / len(path)`. Shorter paths = stronger alpha.
    *   *Magnitude*: Normalizes the `DONATED_TO` edge weight against the max donation in the graph.
3.  Calculates the weighted average based on `config.SCORING_WEIGHTS`.

---

## 4. `src/alpha_engine.py` — Conviction Scoring & LLM
Handles unstructured text processing.

**`calculate_conviction_score(self, event, graph_links)`**
Calculates a score out of 13.5.
*   **Base Score (0-5)**: Based on `graph_links`. If a direct link exists, base score is the `alpha_score` * 5.
*   **Materiality (0-3)**: If it's a contract, what % of the company's market cap is this contract? `score = (contract_value / mcap) * weight`.
*   **Political Alignment (0-2.5)**: Does the issuing state match the party the company donated to? (e.g., UP contract + BJP donation = +2.5).
*   **Competitor Exclusivity (0-3)**: Did they win this on a single bid or against 10 competitors?

**`parse_contract_details(self, text)`**
Uses the Gemini LLM. 
*   **Prompt Engineering**: The prompt strictly enforces a JSON output schema (`{"contract_value_cr": float, "issuing_authority_state": str}`).
*   **Fallback**: If the LLM hits a rate limit or returns malformed JSON, it uses a regex fallback `r"Rs\.?\s*(\d+(?:\.\d+)?)\s*(?:cr|crore)"`.

---

## 5. `src/technical_analyzer.py` — Pure Math Indicators
No external TA libraries used. Pure `pandas` / `numpy`.

**`calculate_rsi(series, period=14)`**
1. Calculates price differences `delta = series.diff()`.
2. Separates into gains (positive) and losses (negative).
3. Uses exponential moving averages (EMA) for the smoothing: `gains.ewm(com=period-1, min_periods=period).mean()`.
4. `RS = EMA(gains) / EMA(losses)`.
5. `RSI = 100 - (100 / (1 + RS))`.

**`calculate_atr(high, low, close, period=14)`**
Used strictly for dynamic stop-losses.
1. Calculates True Range: `TR = max(high-low, abs(high-prev_close), abs(low-prev_close))`.
2. Applies a simple moving average (SMA) over 14 periods to the TR.

---

## 6. `src/portfolio_manager.py` — The Paper Trader
Simulates the real-world mechanics of the Indian stock market.

**`execute_buy(self, symbol, conviction_score)`**
1.  **Kelly Criterion**: Calculates position size. 
    `f = p - (q / b)`
    where `p` is win probability (derived from conviction score, e.g., score 8.0 = 65% win prob), `q` is 1-p, and `b` is the win/loss ratio (assumed 2.0).
2.  **Slippage**: Assumes you get filled at `current_price * 1.005` (0.5% worse than current market price) due to illiquidity in small caps.
3.  **Stop Loss**: Sets the hard stop at `buy_price - (2 * ATR)`.

**`execute_sells(self)`**
The exit logic.
1.  Checks if `current_price <= stop_loss` OR `days_held >= 90` (time stop).
2.  **Taxation Math**:
    *   STT = 0.1% of sell value.
    *   Exchange Txn Charge = 0.00325%.
    *   GST = 18% on the Exchange Charge.
    *   DP Charge = ₹15.93 (flat fee for debiting shares from Demat).
3.  Deducts all taxes from gross PnL to get Net PnL, logs it to `trade_history`, and frees up `available_cash`.

---

## 7. `src/cache_manager.py` — Database & Concurrency
Manages the `data/cache.sqlite` file.

**The WAL Mode Solution**
Because `app.py` (Streamlit) is constantly reading the DB to render the dashboard, and `main.py` (Cron) is writing to it, standard SQLite would throw `database is locked` errors.
```sql
PRAGMA journal_mode=WAL;
```
Write-Ahead Logging allows simultaneous readers and writers.

**Key Tables**:
*   `virtual_portfolio`: Tracks active positions (`buy_price`, `quantity`, `stop_loss`).
*   `trade_history`: Tracks closed positions with `net_pnl`.
*   `alpha_graph`: Caches the heavily computed path queries so the Streamlit dashboard loads instantly without re-running `nx.all_simple_paths`.

---

## 8. `app.py` — The Streamlit Dashboard
The presentation layer.

**`st.cache_data` Optimization**
Functions that query large tables (like `load_portfolio_data()`) are wrapped in `@st.cache_data(ttl=300)`. This means if you refresh the page 10 times in 5 minutes, it only hits the SQLite DB once.

**Gemini Chat Interface**
The "Chat with Data" tab:
1. Grabs the schema of the SQLite DB.
2. Prompts Gemini: "Given this schema, the user asks: [Query]. Return ONLY a valid SQL statement."
3. Executes the returned SQL via `pd.read_sql_query()` and renders the resulting DataFrame using `st.dataframe()`.

---

## 9. `src/backtest.py` — ML Validation
Validates the alpha thesis.

**`run_ml_optimization(self)`**
Instead of simple if/else rules, it trains an `XGBClassifier`.
*   **Target**: 1 if the stock beat the Nifty Smallcap index by >5% over 90 days.
*   **Features**: `conviction_score`, `materiality_pct`, `volume_z_score`, `rsi`.
*   **TimeSeriesSplit**: Standard K-Fold cross-validation leaks future data in finance. `TimeSeriesSplit` ensures the model only trains on past events to predict future events, proving the strategy's real-world viability.
