import logging
import json
# Allow running this file directly (python scripts/research/<name>.py) as well
# as through cli.py. Without this the repo root is not on sys.path and the
# `src` package cannot be imported — a regression introduced when these scripts
# moved out of the repo root.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from src.data.cache_manager import CacheManager
from src.research.backtest import Backtester

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def main():
    cache = CacheManager()
    bt = Backtester(cache)
    report = bt.run_full_backtest()
    print("\n--- BACKTEST REPORT ---")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
