import logging
import json
from src.cache_manager import CacheManager
from src.backtest import Backtester

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def main():
    cache = CacheManager()
    bt = Backtester(cache)
    report = bt.run_full_backtest()
    print("\n--- BACKTEST REPORT ---")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
