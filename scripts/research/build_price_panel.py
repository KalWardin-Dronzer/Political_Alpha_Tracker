"""
Build or refresh the adjusted daily price panel used by the factor engine.

    python build_price_panel.py                 # full universe, 2019 onwards
    python build_price_panel.py --start 2021-01-01
    python build_price_panel.py --limit 200     # smoke test on a subset

Safe to re-run: PriceStore merges into the existing panel rather than
replacing it, so an interrupted run loses nothing.
"""

import argparse
import logging
import sys

from src.data.cache_manager import CacheManager
from src.data.price_store import PriceStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("yfinance").disabled = True
logger = logging.getLogger("build_price_panel")


def universe_symbols(cache: CacheManager, limit: int = None) -> list[str]:
    """Every NSE symbol known to the company cache."""
    sql = (
        "SELECT DISTINCT nse_symbol FROM companies "
        "WHERE nse_symbol IS NOT NULL AND nse_symbol != '' ORDER BY nse_symbol"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    with cache._connect() as conn:
        return [r[0] for r in conn.execute(sql).fetchall()]


def main():
    ap = argparse.ArgumentParser(description="Build the factor engine's price panel.")
    ap.add_argument("--start", default="2019-01-01",
                    help="History start date (default 2019-01-01)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only fetch the first N symbols (smoke test)")
    args = ap.parse_args()

    cache = CacheManager()
    symbols = universe_symbols(cache, args.limit)
    if not symbols:
        logger.error("No NSE symbols in the company cache — nothing to fetch.")
        return 1

    logger.info(f"Universe: {len(symbols)} NSE symbols")
    store = PriceStore()
    store.update(symbols, start=args.start)

    cov = store.coverage()
    logger.info(f"Panel coverage: {cov}")

    adv = store.adv_cr(63)
    if not adv.empty:
        for floor in (0.5, 1.0, 2.0, 5.0):
            logger.info(f"  symbols with ADV >= Rs.{floor:>4.1f} Cr: {int((adv >= floor).sum())}")

    cache.log_event("price_store", "panel_built",
                    f"{cov.get('symbols')} symbols, {cov.get('days')} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
