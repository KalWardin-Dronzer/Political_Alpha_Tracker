import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.cache_manager import CacheManager
from src.portfolio_manager import PaperTrader

logging.basicConfig(level=logging.INFO)

def run_test():
    cache = CacheManager()
    # Init tables if not exists
    cache._init_tables()
    
    trader = PaperTrader(cache)
    
    print("--- BUY SIMULATION ---")
    raw_price = 100.0  # ₹100 per share
    quantity = 1000    # 1000 shares = ₹1,00,000 turnover
    
    exec_price, turnover, total_costs, stt, stamp_duty, txn_charges = trader._calculate_buy_costs(raw_price, quantity)
    
    print(f"Raw Price: Rs.{raw_price}")
    print(f"Exec Price (w/ 0.5% Slippage): Rs.{exec_price}")
    print(f"Turnover: Rs.{turnover}")
    print(f"STT (0.1%): Rs.{stt}")
    print(f"Stamp Duty (0.015%): Rs.{stamp_duty}")
    print(f"Txn Charges: Rs.{txn_charges}")
    print(f"Total Buy Taxes/Costs: Rs.{total_costs}")
    print(f"Total Outflow: Rs.{turnover + total_costs}")
    
    print("\n--- SELL SIMULATION ---")
    exec_price, turnover, total_costs, stt, txn_charges = trader._calculate_sell_costs(raw_price, quantity)
    
    print(f"Raw Price: Rs.{raw_price}")
    print(f"Exec Price (w/ 0.5% Slippage): Rs.{exec_price}")
    print(f"Turnover: Rs.{turnover}")
    print(f"STT (0.1%): Rs.{stt}")
    print(f"Txn Charges: Rs.{txn_charges}")
    print(f"DP Charges: Rs.{trader.dp_charge}")
    print(f"Total Sell Taxes/Costs: Rs.{total_costs}")
    print(f"Total Inflow: Rs.{turnover - total_costs}")

if __name__ == "__main__":
    run_test()
