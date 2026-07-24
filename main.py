"""
Political Alpha Tracker — Daily Pipeline Orchestrator

The central traffic controller run by GitHub Actions daily at 6 PM IST.

Pipeline sequence:
    1. Poll Telegram for /exit commands
    2. Scan BSE announcements for watchlist + held positions
    3. For each new contract announcement:
        a. Run fundamental screening
        b. Ensure directors are resolved (MCA)
        c. Run Alpha Query on graph
        d. If score >= threshold, fire Telegram alert
    4. For each board change:
        a. Trigger MCA director refresh
    5. Send daily summary
    6. Save graph state
"""

import sys
import logging
import argparse
from datetime import datetime

from src.config import (
    ALPHA_SCORE_THRESHOLD, DATA_DIR, MCA_CACHE_TTL_DAYS,
)
from src.cache_manager import CacheManager
from src.bse_monitor import BSEMonitor
from src.financial_screener import FinancialScreener
from src.mca_resolver import MCAResolver
from src.entity_resolver import EntityResolver
from src.graph_manager import GraphManager
from src.notifier import Notifier
from src.watchlist_generator import WatchlistGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            DATA_DIR / "pipeline.log",
            mode="a",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("main")


def run_daily_pipeline(dry_run: bool = False):
    """
    Execute the full daily pipeline.

    Args:
        dry_run: If True, skip Telegram alerts and graph writes.
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"DAILY PIPELINE STARTED — {start_time.strftime('%Y-%m-%d %H:%M IST')}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info("=" * 60)

    # Initialize modules
    cache = CacheManager()
    bse = BSEMonitor(cache)
    screener = FinancialScreener(cache)
    mca = MCAResolver(cache)
    entity = EntityResolver(cache)
    graph = GraphManager(cache)
    notifier = Notifier(cache)
    watchlist_gen = WatchlistGenerator(cache)

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Poll Telegram for /exit commands ──
    logger.info("Step 1: Polling Telegram for /exit commands...")
    if not dry_run:
        removed = notifier.poll_exit_commands()
        if removed:
            logger.info(f"Removed positions: {removed}")
    else:
        logger.info("  [DRY RUN] Skipping Telegram poll")

    # ── Step 2: Get monitoring list ──
    logger.info("Step 2: Building monitoring list...")
    scrip_codes = watchlist_gen.get_monitoring_scrip_codes()

    if not scrip_codes:
        logger.warning("No scrip codes to monitor. Is the watchlist empty?")
        logger.warning("Run 'python refresh.py --mode quarterly' to generate watchlist.")

        if not dry_run:
            notifier.send_system_alert(
                "Empty Watchlist",
                "No companies to monitor. Run quarterly refresh.",
                "WARNING",
            )
        return

    logger.info(f"Monitoring {len(scrip_codes)} scrip codes")

    # ── Step 3: Scan BSE announcements ──
    logger.info("Step 3: Scanning BSE announcements...")
    events = bse.scan_watchlist(scrip_codes, lookback_days=1)

    contracts = [e for e in events if e.event_type == "contract"]
    board_changes = [e for e in events if e.event_type == "board_change"]

    logger.info(
        f"Found {len(contracts)} contract events, "
        f"{len(board_changes)} board changes"
    )

    # ── Step 4: Process board changes (trigger MCA refresh) ──
    if board_changes:
        logger.info("Step 4: Processing board changes...")
        for event in board_changes:
            company = cache.get_company(event.scrip_code)
            if company and company.get("cin"):
                logger.info(
                    f"  Board change at {event.company_name} — "
                    f"refreshing directors"
                )
                mca.resolve_directors(company["cin"], force_refresh=True)

    # ── Step 5: Process contract events ──
    alerts_fired = 0

    if contracts:
        logger.info("Step 5: Processing contract events...")

        for event in contracts:
            logger.info(
                f"\n{'─' * 40}\n"
                f"Contract: {event.company_name} ({event.scrip_code})\n"
                f"Title: {event.title}\n"
                f"Date: {event.date}\n"
                f"{'─' * 40}"
            )

            # 5a: Fundamental screening
            result = screener.screen(event.scrip_code, event.company_name)
            if not result.passes:
                logger.info(
                    f"  ❌ Failed fundamentals: {result.reason}. Skipping."
                )
                continue

            logger.info(f"  ✅ Passed fundamentals: {result.summary()}")

            # 5b: Ensure directors are resolved
            company = cache.get_company(event.scrip_code)
            if not company or not company.get("cin"):
                logger.warning(
                    f"  No CIN for {event.scrip_code}. "
                    f"Cannot run Alpha Query."
                )
                continue

            cin = company["cin"]

            if not cache.is_director_cache_fresh(cin, MCA_CACHE_TTL_DAYS):
                logger.info(f"  Refreshing directors for {cin}...")
                mca.resolve_directors(cin)

            # 5c: Rebuild graph context and run Alpha Query
            graph.build_from_cache()
            connections = graph.alpha_query(cin)

            if not connections:
                logger.info(f"  No political connections found for {cin}")
                continue

            # 5d: Check threshold and alert
            top_connection = connections[0]
            score = top_connection["alpha_score"]

            logger.info(
                f"  🔗 Top connection: score={score:.2f}, "
                f"director={top_connection['director_name']}, "
                f"donor={top_connection['donor_company_name']}"
            )

            if score >= ALPHA_SCORE_THRESHOLD:
                logger.info(f"  🚨 Score {score:.2f} >= threshold. ALERTING!")

                # Add tender to graph
                tender_id = graph.add_tender(
                    title=event.title,
                    date=event.date,
                    scrip_code=event.scrip_code,
                )
                graph.link_company_to_tender(cin, tender_id)

                if not dry_run:
                    notifier.send_alpha_alert(
                        connection=top_connection,
                        fundamental=result,
                        announcement={
                            "title": event.title,
                            "date": event.date,
                        },
                    )
                    alerts_fired += 1
                else:
                    logger.info("  [DRY RUN] Would have sent alert")
                    alerts_fired += 1
            else:
                logger.info(
                    f"  Score {score:.2f} < threshold "
                    f"{ALPHA_SCORE_THRESHOLD}. No alert."
                )
    else:
        logger.info("Step 5: No contract events to process")

    # ── Step 6: Save graph and send summary ──
    logger.info("Step 6: Saving graph and sending summary...")

    if not dry_run:
        graph.save()

        notifier.send_daily_summary(
            contracts_found=len(contracts),
            alerts_fired=alerts_fired,
            watchlist_size=len(scrip_codes),
            graph_stats=graph.get_stats(),
        )

    # Log completion
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info(
        f"DAILY PIPELINE COMPLETE — "
        f"{elapsed:.1f}s elapsed, "
        f"{len(contracts)} contracts, "
        f"{alerts_fired} alerts"
    )
    logger.info("=" * 60)

    cache.log_event(
        "main", "pipeline_complete",
        f"Elapsed: {elapsed:.1f}s, "
        f"Contracts: {len(contracts)}, Alerts: {alerts_fired}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Political Alpha Tracker — Daily Pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending alerts or writing to graph",
    )
    args = parser.parse_args()

    try:
        run_daily_pipeline(dry_run=args.dry_run)
    except Exception as e:
        logger.exception(f"Pipeline failed with error: {e}")
        # Try to send error alert
        try:
            cache = CacheManager()
            notifier = Notifier(cache)
            notifier.send_system_alert(
                "Pipeline Failure",
                f"Daily pipeline crashed:\n{str(e)[:500]}",
                "ERROR",
            )
        except Exception:
            pass
        sys.exit(1)
