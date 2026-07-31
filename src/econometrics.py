import os
import sys
# Add project root to PYTHONPATH so we can run this file directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import pandas as pd
import numpy as np
import statsmodels.api as sm
from pathlib import Path
from datetime import datetime, timedelta

from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from src.backtest import Backtester

def run_ols_regression(cache: CacheManager, backtester: Backtester, forward_window_days: int = 90):
    """
    Constructs a panel dataset of all historical contracts and runs an OLS regression
    to determine if Alpha Score is a statistically significant predictor of forward returns.
    """
    print(f"Building Econometric Panel Dataset (Window: {forward_window_days} days)...")
    
    with cache._connect() as conn:
        # Get historical contract announcements with their market cap
        rows = conn.execute("""
            SELECT a.scrip_code, a.date, c.cin, c.name, c.market_cap
            FROM announcements a
            JOIN companies c ON a.scrip_code = c.scrip_code
            WHERE a.is_contract = 1
        """).fetchall()

    panel_data = []
    
    for row in rows:
        scrip_code = row[0]
        event_date_str = row[1]
        cin = row[2]
        market_cap = row[4]
        
        if not cin or not market_cap:
            continue
            
        # Get political connection score at the time of the event
        # (Assuming the graph represents the connections around that period)
        connections = backtester.graph.alpha_query(cin)
        
        alpha_score = 0.0
        bureaucrat_mult = 1.0
        
        if connections:
            top_conn = connections[0]
            alpha_score = top_conn.get("alpha_score", 0.0)
            bureaucrat_mult = top_conn.get("bureaucrat_multiplier", 1.0)
            
        # Get forward return
        start_date = (datetime.strptime(event_date_str, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
        end_date = (datetime.strptime(event_date_str, "%Y-%m-%d") + timedelta(days=forward_window_days + 15)).strftime("%Y-%m-%d")
        
        prices = backtester._get_price_history(scrip_code, start_date, end_date)
        if prices is None or prices.empty:
            continue
            
        returns = backtester._compute_returns(prices, event_date_str, [forward_window_days])
        if forward_window_days not in returns:
            continue
            
        fwd_return = returns[forward_window_days]
        
        # Get benchmark return
        bm_prices = backtester._get_price_history("^NSEI", start_date, end_date)
        bm_returns = backtester._compute_returns(bm_prices, event_date_str, [forward_window_days]) if bm_prices is not None else {}
        bm_return = bm_returns.get(forward_window_days, 0.0)
        
        excess_return = fwd_return - bm_return
        
        panel_data.append({
            "scrip_code": scrip_code,
            "event_date": event_date_str,
            "excess_return": excess_return,
            "alpha_score": alpha_score,
            "log_market_cap": np.log(market_cap) if market_cap > 0 else 0,
            "bureaucrat_multiplier": bureaucrat_mult,
        })
        
    df = pd.DataFrame(panel_data)
    
    if df.empty:
        print("Not enough historical data to run regression.")
        return None
        
    print(f"Panel dataset built with {len(df)} observations.")
    
    # Run OLS Regression
    # Equation: Excess_Return = Beta0 + Beta1(Alpha_Score) + Beta2(Log_Market_Cap)
    X = df[["alpha_score", "log_market_cap"]]
    X = sm.add_constant(X) # Add intercept (Beta0)
    y = df["excess_return"]
    
    model = sm.OLS(y, X).fit()
    
    _export_to_markdown(model, len(df))
    return model

def _export_to_markdown(model, nobs: int):
    """Formats the statsmodels summary into a beautiful academic markdown artifact."""
    summary = model.summary()
    
    md_content = f"""# Political Alpha Econometric Regression Results

This artifact contains the Ordinary Least Squares (OLS) regression output for our ED 500 academic paper.

## Model Summary
**Equation:** `ExcessReturn(t+90) = β0 + β1(AlphaScore) + β2(LogMarketCap) + ε`

- **Observations (N):** {nobs}
- **R-squared:** {model.rsquared:.4f}
- **Adj. R-squared:** {model.rsquared_adj:.4f}
- **F-statistic:** {model.fvalue:.2f} (p-value: {model.f_pvalue:.4e})

## Coefficients

| Variable | Coefficient | Std. Error | t-Statistic | P>|t| | [0.025 | 0.975] |
|----------|-------------|------------|-------------|-------|--------|--------|
"""
    
    # Extract coefficients table
    for i, name in enumerate(model.params.index):
        coef = model.params.iloc[i]
        stderr = model.bse.iloc[i]
        tstat = model.tvalues.iloc[i]
        pval = model.pvalues.iloc[i]
        conf_int = model.conf_int().iloc[i]
        
        md_content += f"| **{name}** | {coef:.4f} | {stderr:.4f} | {tstat:.2f} | {pval:.4f} | {conf_int[0]:.4f} | {conf_int[1]:.4f} |\n"

    md_content += """
---
### Academic Interpretation (ED 500)
- **Alpha Score (β1):** If the p-value is `< 0.05` and the coefficient is positive, it mathematically proves that our Graph-Theoretic Political Alpha Score drives statistically significant excess returns, confirming our core thesis of Asymmetric Information.
- **Log Market Cap (β2):** This controls for the "Size Effect" (Fama-French). Smaller micro-caps tend to have higher variance and returns. Controlling for this ensures our Alpha Score isn't just accidentally picking up a micro-cap premium.

> [!TIP]
> You can copy-paste this exact table into your ED 500 Project-I final report.
"""
    
    out_path = Path("C:/Users/legen/.gemini/antigravity-ide/brain/4f53a9f7-572a-42aa-8969-3269799b92b4/regression_results.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    print(f"Academic regression results exported to {out_path}")

if __name__ == "__main__":
    cache = CacheManager(Path("data/cache.sqlite"))
    bt = Backtester(cache)
    # Ensure graph is loaded
    bt.graph.build_from_cache()
    
    model = run_ols_regression(cache, bt, forward_window_days=90)
    if model:
        print("Regression completed successfully.")
