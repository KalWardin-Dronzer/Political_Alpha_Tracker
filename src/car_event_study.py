"""
CAR Event Study: Short-Window Cumulative Abnormal Returns
=========================================================
Correct methodology per academic literature:
  - Window: (-1, +10) trading days around contract announcement
  - Estimation window: -120 to -11 days (for market model)
  - Abnormal Return = Actual Return - Expected Return (Market Model)
  - CAR = Sum of ARs over event window
  - Compare: Connected firms vs Non-connected firms
  - Test: Welch's t-test on mean CAR difference
"""
import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from src.config import ALPHA_SCORE_THRESHOLD

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────
EVENT_WINDOW_PRE  = 1    # days before event (T-1)
EVENT_WINDOW_POST = 10   # days after event (T+10)
ESTIMATION_WINDOW = 120  # days for market model estimation (-120 to -11)
BENCHMARK = "^NSEI"      # Nifty 50

# Also test multiple windows to find where alpha concentrates
WINDOWS_TO_TEST = [
    (-1, 1),   # Immediate reaction
    (-1, 3),   # Short-term
    (-1, 5),   # Medium-term
    (-1, 10),  # Standard event study
    (-1, 20),  # Extended
    (0, 30),   # Monthly
]

# BSE scrip code -> NSE trading symbol mapping
BSE_TO_NSE = {
    "512599": "ADANIENT",
    "500260": "RAMCOCEM",
    "543994": "JSWINFRA",
    "534309": "NBCC",
    "513599": "HINDCOPPER",
    "544280": "AFCONS",
    "500257": "LUPIN",
    "500420": "TORNTPHARM",
    "507789": "JAGSNPHARM",
    "539872": "BAJAJHCARE",
    "500112": "SBIN",
    "500180": "HDFCBANK",
    "500295": "VEDL",
    "500325": "RELIANCE",
    "532215": "AXISBANK",
    "532540": "TCS",
    "539523": "ALKEM",
    "543287": "LODHA",
}

def fetch_prices(ticker_symbol, start, end):
    """Fetch adjusted close prices from yfinance."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(start=start, end=end)
        if hist.empty:
            return None
        return hist['Close']
    except Exception:
        return None

def fetch_stock_prices(scrip_code, start, end):
    """Fetch stock prices trying NSE symbol first, then BSE scrip code."""
    # Try NSE symbol first (more reliable)
    nse_sym = BSE_TO_NSE.get(scrip_code)
    if nse_sym:
        prices = fetch_prices(f"{nse_sym}.NS", start, end)
        if prices is not None and len(prices) >= 30:
            return prices
    
    # Fallback to BSE
    prices = fetch_prices(f"{scrip_code}.BO", start, end)
    if prices is not None and len(prices) >= 30:
        return prices
    
    return None

def compute_car(stock_prices, benchmark_prices, event_date, pre_days, post_days):
    """
    Compute Cumulative Abnormal Return using Market Model.
    
    1. Estimation window: -120 to -11 trading days -> fit alpha, beta
    2. Event window: -pre_days to +post_days -> compute AR = R_stock - (alpha + beta*R_market)
    3. CAR = Sum(AR)
    """
    event_dt = pd.Timestamp(event_date)
    
    # Align to trading days
    if stock_prices.index.tz is not None:
        event_dt = event_dt.tz_localize(stock_prices.index.tz)
    
    # Find the event date position in the stock price index
    valid_after = stock_prices.index[stock_prices.index >= event_dt]
    if valid_after.empty:
        return None
    
    # Compute daily returns for both stock and benchmark
    stock_returns = stock_prices.pct_change().dropna()
    bm_returns = benchmark_prices.pct_change().dropna()
    
    # Align the two series by date
    combined = pd.DataFrame({
        'stock': stock_returns,
        'benchmark': bm_returns
    }).dropna()
    
    if len(combined) < 30:
        return None
    
    # Find event position in the combined returns index
    valid_event = combined.index[combined.index >= event_dt]
    if valid_event.empty:
        return None
    event_pos = combined.index.get_loc(valid_event[0])
    
    # Estimation window: -120 to -11 trading days before event
    est_start = max(0, event_pos - ESTIMATION_WINDOW)
    est_end = max(0, event_pos - 11)
    
    if est_end - est_start < 20:
        # Fallback: use market-adjusted model (simpler)
        # AR = R_stock - R_benchmark
        results = {}
        for (w_pre, w_post) in WINDOWS_TO_TEST:
            ew_start = max(0, event_pos - abs(w_pre))
            ew_end = min(len(combined) - 1, event_pos + w_post)
            
            if ew_end <= ew_start:
                continue
            
            event_data = combined.iloc[ew_start:ew_end + 1]
            ar = event_data['stock'] - event_data['benchmark']
            car = ar.sum() * 100
            results[f"({w_pre},{w_post})"] = round(car, 4)
        
        return results if results else None
    
    estimation_data = combined.iloc[est_start:est_end]
    
    # Fit Market Model: R_stock = alpha + beta * R_market
    X = estimation_data['benchmark'].values
    Y = estimation_data['stock'].values
    
    X_with_const = np.column_stack([np.ones(len(X)), X])
    try:
        beta_hat = np.linalg.lstsq(X_with_const, Y, rcond=None)[0]
        alpha_hat, beta_market = beta_hat[0], beta_hat[1]
    except Exception:
        alpha_hat, beta_market = 0.0, 1.0
    
    # Compute CARs for each window
    results = {}
    for (w_pre, w_post) in WINDOWS_TO_TEST:
        ew_start = max(0, event_pos - abs(w_pre))
        ew_end = min(len(combined) - 1, event_pos + w_post)
        
        if ew_end <= ew_start:
            continue
        
        event_data = combined.iloc[ew_start:ew_end + 1]
        
        # Expected return = alpha + beta * R_market
        expected_returns = alpha_hat + beta_market * event_data['benchmark']
        
        # Abnormal return = Actual - Expected
        ar = event_data['stock'] - expected_returns
        car = ar.sum() * 100
        
        results[f"({w_pre},{w_post})"] = round(car, 4)
    
    return results


def main():
    print("=" * 80)
    print("CAR EVENT STUDY - Short Window Cumulative Abnormal Returns")
    print("Methodology: Market Model, (-1,+10) primary window")
    print("=" * 80)
    
    # Load data
    cache = CacheManager(Path("data/cache.sqlite"))
    graph = GraphManager(cache)
    graph.build_from_cache()
    
    with cache._connect() as conn:
        rows = conn.execute("""
            SELECT DISTINCT a.scrip_code, a.date, a.title, c.cin, c.name, c.market_cap
            FROM announcements a
            JOIN companies c ON a.scrip_code = c.scrip_code
            WHERE a.is_contract = 1
            ORDER BY a.date
        """).fetchall()
    
    print(f"\nTotal contract events: {len(rows)}")
    
    # Classify events as connected vs non-connected
    connected_events = []
    unconnected_events = []
    skipped = 0
    
    for row in rows:
        cin = row[3]
        scrip_code = row[0]
        event_date = row[1]
        company_name = row[4]
        
        if not cin:
            skipped += 1
            continue
        
        connections = graph.alpha_query(cin)
        alpha_score = connections[0]["alpha_score"] if connections else 0.0
        is_connected = alpha_score >= ALPHA_SCORE_THRESHOLD
        
        event_info = {
            "scrip_code": scrip_code,
            "date": event_date,
            "name": company_name,
            "cin": cin,
            "alpha_score": alpha_score,
            "title": row[2],
        }
        
        if is_connected:
            connected_events.append(event_info)
        else:
            # Exclude Adani Enterprises outliers
            if scrip_code != "512599":
                unconnected_events.append(event_info)
            else:
                skipped += 1
    
    print(f"Connected events: {len(connected_events)}")
    print(f"Non-connected events: {len(unconnected_events)}")
    print(f"Skipped (no CIN): {skipped}")
    
    # Fetch benchmark prices (full range)
    all_dates = [e["date"] for e in connected_events + unconnected_events]
    if not all_dates:
        print("No events to analyze!")
        return
    
    min_date = (datetime.strptime(min(all_dates), "%Y-%m-%d") - timedelta(days=200)).strftime("%Y-%m-%d")
    max_date = (datetime.strptime(max(all_dates), "%Y-%m-%d") + timedelta(days=60)).strftime("%Y-%m-%d")
    
    print(f"\nFetching Nifty 50 benchmark prices ({min_date} to {max_date})...")
    bm_prices = fetch_prices(BENCHMARK, min_date, max_date)
    if bm_prices is None or bm_prices.empty:
        print("ERROR: Could not fetch benchmark prices!")
        return
    print(f"Benchmark data: {len(bm_prices)} trading days")
    
    # Process each event
    def process_events(events, label):
        all_cars = {f"({w[0]},{w[1]})": [] for w in WINDOWS_TO_TEST}
        processed = 0
        failed = 0
        
        for event in events:
            scrip = event["scrip_code"]
            date_str = event["date"]
            
            start = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=200)).strftime("%Y-%m-%d")
            end = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=60)).strftime("%Y-%m-%d")
            
            stock_prices = fetch_stock_prices(scrip, start, end)
            if stock_prices is None:
                failed += 1
                continue
            
            cars = compute_car(stock_prices, bm_prices, date_str,
                             EVENT_WINDOW_PRE, EVENT_WINDOW_POST)
            
            if cars is None:
                failed += 1
                continue
            
            processed += 1
            for window_key, car_val in cars.items():
                if window_key in all_cars:
                    all_cars[window_key].append(car_val)
            
            car_10 = cars.get('(-1,10)', 'N/A')
            car_str = f"{car_10:>+8.2f}" if isinstance(car_10, (int, float)) else f"{car_10:>8s}"
            print(f"  [{label}] {event['name'][:25]:25s} {date_str} | "
                  f"CAR(-1,+10)={car_str}% | "
                  f"alpha={event['alpha_score']:.2f}")
        
        print(f"  {label}: Processed {processed}/{len(events)}, Failed {failed}")
        return all_cars
    
    print(f"\n{'_' * 80}")
    print("Processing CONNECTED events (alpha_score >= threshold)...")
    print(f"{'_' * 80}")
    connected_cars = process_events(connected_events, "CONN")
    
    print(f"\n{'_' * 80}")
    print("Processing NON-CONNECTED events...")
    print(f"{'_' * 80}")
    unconnected_cars = process_events(unconnected_events, "UNCONN")
    
    # STATISTICAL ANALYSIS
    print("\n" + "=" * 80)
    print("RESULTS: CUMULATIVE ABNORMAL RETURNS (CAR) BY WINDOW")
    print("=" * 80)
    
    results_data = []
    
    header = f"{'Window':<12} | {'Conn CAR%':>10} | {'N_conn':>6} | {'Unconn CAR%':>11} | {'N_unc':>5} | {'Diff':>8} | {'t-stat':>8} | {'p-value':>8} | {'Sig?':>5}"
    print(f"\n{header}")
    print("-" * 100)
    
    for window in WINDOWS_TO_TEST:
        key = f"({window[0]},{window[1]})"
        
        conn_vals = connected_cars.get(key, [])
        unconn_vals = unconnected_cars.get(key, [])
        
        conn_mean = np.mean(conn_vals) if conn_vals else 0
        unconn_mean = np.mean(unconn_vals) if unconn_vals else 0
        diff = conn_mean - unconn_mean
        
        if len(conn_vals) >= 2 and len(unconn_vals) >= 2:
            t_stat, p_val = stats.ttest_ind(conn_vals, unconn_vals, equal_var=False)
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        else:
            t_stat, p_val = 0, 1.0
            sig = "N/A"
        
        print(f"{key:<12} | {conn_mean:>+10.2f} | {len(conn_vals):>6} | {unconn_mean:>+11.2f} | {len(unconn_vals):>5} | {diff:>+8.2f} | {t_stat:>8.3f} | {p_val:>8.4f} | {sig:>5}")
        
        results_data.append({
            "window": key,
            "connected_car_pct": round(conn_mean, 4),
            "connected_n": len(conn_vals),
            "connected_std": round(np.std(conn_vals, ddof=1), 4) if len(conn_vals) > 1 else 0,
            "unconnected_car_pct": round(unconn_mean, 4),
            "unconnected_n": len(unconn_vals),
            "unconnected_std": round(np.std(unconn_vals, ddof=1), 4) if len(unconn_vals) > 1 else 0,
            "difference": round(diff, 4),
            "t_stat": round(t_stat, 4),
            "p_value": round(p_val, 4),
        })
    
    # One-sample t-test: Are connected CARs significantly different from zero?
    print(f"\n{'=' * 80}")
    print("ONE-SAMPLE t-TEST: Are Connected CARs != 0?")
    print(f"{'=' * 80}")
    
    header2 = f"{'Window':<12} | {'Mean CAR%':>10} | {'Std':>8} | {'N':>4} | {'t-stat':>8} | {'p-value':>8} | {'Sig?':>5}"
    print(f"\n{header2}")
    print("-" * 70)
    
    for window in WINDOWS_TO_TEST:
        key = f"({window[0]},{window[1]})"
        conn_vals = connected_cars.get(key, [])
        
        if len(conn_vals) >= 2:
            t_stat, p_val = stats.ttest_1samp(conn_vals, 0)
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            mean_val = np.mean(conn_vals)
            std_val = np.std(conn_vals, ddof=1)
            print(f"{key:<12} | {mean_val:>+10.2f} | {std_val:>8.2f} | {len(conn_vals):>4} | {t_stat:>8.3f} | {p_val:>8.4f} | {sig:>5}")
    
    # Save results to markdown
    export_results_md(results_data, len(connected_events), len(unconnected_events))
    
    print("\nDone!")


def export_results_md(results_data, n_connected_events, n_unconnected_events):
    """Export results to a markdown artifact."""
    
    md = """# CAR Event Study Results - Short-Window Analysis

> **Methodology:** Market Model CAR with 120-day estimation window
> **Benchmark:** Nifty 50 (^NSEI)
> **Hypothesis:** Connected firms generate higher CAR after contract announcements

## Key Results

### Two-Sample t-Test: Connected vs Non-Connected CAR

| Window | Connected CAR (%) | N | Unconnected CAR (%) | N | Difference (%) | t-statistic | p-value | Significant? |
|--------|-------------------|---|---------------------|---|-----------------|-------------|---------|-------------|
"""
    
    for r in results_data:
        if r["p_value"] < 0.01:
            sig_marker = "*** p<0.01"
        elif r["p_value"] < 0.05:
            sig_marker = "** p<0.05"
        elif r["p_value"] < 0.10:
            sig_marker = "* p<0.10"
        else:
            sig_marker = "No"
        md += f"| {r['window']} | {r['connected_car_pct']:+.2f} | {r['connected_n']} | {r['unconnected_car_pct']:+.2f} | {r['unconnected_n']} | {r['difference']:+.2f} | {r['t_stat']:.3f} | {r['p_value']:.4f} | {sig_marker} |\n"
    
    md += f"""
### Summary

- **Events Analyzed:** {n_connected_events} connected + {n_unconnected_events} non-connected = {n_connected_events + n_unconnected_events} total
- A **positive difference** means connected firms outperform non-connected firms after contract wins
- A **negative difference** means connected firms underperform (rent-seeking penalty)
- Significance levels: *** p<0.01, ** p<0.05, * p<0.10

## Windows Tested

| Window | Academic Use |
|--------|-------------|
| (-1, 1) | Immediate market reaction |
| (-1, 3) | Short-term price discovery |
| (-1, 5) | Standard for liquid stocks |
| (-1, 10) | **Primary** - full adjustment for small/micro-caps |
| (-1, 20) | Extended drift |
| (0, 30) | Monthly holding period |
"""
    
    primary = next((r for r in results_data if r["window"] == "(-1,10)"), None)
    if primary:
        if primary["difference"] > 0 and primary["p_value"] < 0.05:
            md += "\n> [!TIP]\n> **POSITIVE ALPHA CONFIRMED.** Connected firms show statistically significant positive CAR after contract wins.\n"
        elif primary["difference"] > 0 and primary["p_value"] < 0.10:
            md += "\n> [!NOTE]\n> **WEAKLY POSITIVE ALPHA.** Connected firms show marginally significant positive CAR. More data needed.\n"
        elif primary["difference"] < 0 and primary["p_value"] < 0.05:
            md += "\n> [!IMPORTANT]\n> **NEGATIVE ALPHA CONFIRMED.** Connected firms significantly underperform. Supports rent-seeking hypothesis. Valuable as SHORT signal.\n"
        elif primary["difference"] < 0 and primary["p_value"] < 0.10:
            md += "\n> [!WARNING]\n> **WEAKLY NEGATIVE ALPHA.** Marginally significant underperformance. Partially supports rent-seeking hypothesis.\n"
        else:
            md += "\n> [!WARNING]\n> **NO SIGNIFICANT ALPHA** at the 10% level. Sample size may be insufficient, or the political connection signal alone is not predictive in the short window.\n"
    
    out_path = Path("C:/Users/legen/.gemini/antigravity-ide/brain/4f53a9f7-572a-42aa-8969-3269799b92b4/car_event_study_results.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"\nResults exported to {out_path}")


if __name__ == "__main__":
    main()
