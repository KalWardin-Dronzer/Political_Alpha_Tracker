import logging
import json
from src.cache_manager import CacheManager
from src.backtest import Backtester

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def main():
    cache = CacheManager()
    backtester = Backtester(cache)
    print("Running test_ml_optimization...")
    result = backtester.test_ml_optimization()
    print("Result:")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
