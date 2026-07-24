"""
Political Alpha Tracker — Refresh Orchestrator

Handles quarterly and annual refresh operations:
    --mode quarterly: Regenerate watchlist + refresh MCA directors + rebuild graph
    --mode annual:    Update Electoral Trust donor data + re-resolve entities
    --mode prune:     Run weekly graph pruning
"""

import sys
import logging
import argparse
from datetime import datetime

from src.config import DATA_DIR
from src.cache_manager import CacheManager
from src.watchlist_generator import WatchlistGenerator
from src.mca_resolver import MCAResolver
from src.entity_resolver import EntityResolver
from src.donor_ingester import DonorIngester
from src.graph_manager import GraphManager
from src.notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            DATA_DIR / "refresh.log",
            mode="a",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("refresh")


def quarterly_refresh():
    """
    Quarterly refresh: regenerate watchlist, refresh directors, rebuild graph.
    Runs on 1st of Jan/Apr/Jul/Oct.
    """
    logger.info("=" * 60)
    logger.info("QUARTERLY REFRESH STARTED")
    logger.info("=" * 60)

    cache = CacheManager()
    notifier = Notifier(cache)

    # Step 1: Regenerate watchlist
    logger.info("Step 1: Regenerating watchlist...")
    generator = WatchlistGenerator(cache)
    watchlist = generator.generate()
    logger.info(f"New watchlist: {len(watchlist)} companies")

    # Step 2: Refresh MCA directors for all watchlist companies
    logger.info("Step 2: Refreshing MCA directors...")
    mca = MCAResolver(cache)
    cins = [c.get("cin") for c in watchlist if c.get("cin")]
    if cins:
        mca.resolve_batch(cins, force_refresh=True)

    # Step 3: Re-resolve entities
    logger.info("Step 3: Re-resolving entities...")
    entity = EntityResolver(cache)
    entity.invalidate_caches()
    resolution = entity.resolve_all_donors()
    logger.info(
        f"Entity resolution: {resolution['resolved']}/{resolution['total']} "
        f"donors resolved"
    )

    # Step 4: Rebuild graph
    logger.info("Step 4: Rebuilding graph...")
    graph = GraphManager(cache)
    graph.build_from_cache()
    graph.save()

    stats = graph.get_stats()
    logger.info(f"Graph: {stats}")

    # Send summary
    notifier.send_system_alert(
        "Quarterly Refresh Complete",
        f"Watchlist: {len(watchlist)} companies\n"
        f"Directors resolved: {len(cins)} companies\n"
        f"Donors: {resolution['resolved']}/{resolution['total']} resolved\n"
        f"Graph: {stats['total_nodes']} nodes, {stats['total_edges']} edges",
    )

    cache.log_event("refresh", "quarterly_complete", str(stats))
    logger.info("QUARTERLY REFRESH COMPLETE")


def annual_refresh():
    """
    Annual refresh: update Electoral Trust donor data.
    Runs in March after ADR publishes new FY data.
    """
    logger.info("=" * 60)
    logger.info("ANNUAL DONOR REFRESH STARTED")
    logger.info("=" * 60)

    cache = CacheManager()
    notifier = Notifier(cache)

    # Step 1: Ingest new donor data
    logger.info("Step 1: Ingesting donor data...")
    ingester = DonorIngester(cache)
    count = ingester.ingest_all()
    logger.info(f"Ingested {count} donor records")

    # Step 2: Resolve donor CINs
    logger.info("Step 2: Resolving donor CINs...")
    entity = EntityResolver(cache)
    entity.invalidate_caches()
    resolution = entity.resolve_all_donors()

    # Step 3: Rebuild graph with new data
    logger.info("Step 3: Rebuilding graph...")
    graph = GraphManager(cache)
    graph.build_from_cache()
    graph.save()

    stats = graph.get_stats()

    notifier.send_system_alert(
        "Annual Donor Refresh Complete",
        f"New donor records: {count}\n"
        f"Donors resolved: {resolution['resolved']}/{resolution['total']}\n"
        f"Unresolved: {', '.join(resolution['unresolved_names'][:10])}\n"
        f"Graph: {stats['total_nodes']} nodes, {stats['total_edges']} edges",
    )

    cache.log_event("refresh", "annual_complete", str(stats))
    logger.info("ANNUAL DONOR REFRESH COMPLETE")


def weekly_prune():
    """
    Weekly prune: clean up stale graph nodes and expired held positions.
    Runs every Sunday.
    """
    logger.info("WEEKLY PRUNE STARTED")

    cache = CacheManager()

    # Prune graph
    graph = GraphManager(cache)
    graph.prune()
    graph.save()

    # Cleanup expired positions
    expired = cache.cleanup_expired_positions()
    if expired:
        logger.info(f"Expired {expired} held positions")

    stats = graph.get_stats()
    cache.log_event("refresh", "weekly_prune", str(stats))

    logger.info(f"WEEKLY PRUNE COMPLETE — Graph: {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Political Alpha Tracker — Refresh Operations"
    )
    parser.add_argument(
        "--mode",
        choices=["quarterly", "annual", "prune"],
        required=True,
        help="Refresh mode to execute",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if args.mode == "quarterly":
            quarterly_refresh()
        elif args.mode == "annual":
            annual_refresh()
        elif args.mode == "prune":
            weekly_prune()
    except Exception as e:
        logger.exception(f"Refresh failed: {e}")
        try:
            cache = CacheManager()
            notifier = Notifier(cache)
            notifier.send_system_alert(
                f"Refresh Failure ({args.mode})",
                f"Refresh crashed:\n{str(e)[:500]}",
                "ERROR",
            )
        except Exception:
            pass
        sys.exit(1)
