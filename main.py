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

# Fix Windows console emoji printing
if sys.stdout.encoding != 'utf-8' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

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
from src.universe_manager import UniverseManager
from src.tender_monitor import TenderMonitor
from src.state_budget_monitor import StateBudgetMonitor
from src.pledge_monitor import PledgeMonitor
from src.portfolio_manager import PaperTrader

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
    tender_monitor = TenderMonitor(cache, notifier, graph)
    state_budget_monitor = StateBudgetMonitor(cache, notifier, graph)
    pledge_monitor = PledgeMonitor(cache, notifier, graph)
    paper_trader = PaperTrader(cache)

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
    logger.info("Step 2: Building full universe monitoring list...")
    universe_manager = UniverseManager(cache)
    
    # Normally we'd update_universe() here, but we will run it via a separate cron/script 
    # to prevent daily pipeline delays, or we can just call it (it limits to 50 missing anyway).
    universe_manager.update_universe()
    
    scrip_codes = universe_manager.get_full_universe_scrip_codes()

    if not scrip_codes:
        logger.warning("No scrip codes to monitor. Is the universe empty?")
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

    # ── Step 3.5: Execute Virtual Sells ──
    if not dry_run:
        logger.info("Step 3.5: Checking virtual portfolio for 90-day sells...")
        paper_trader.execute_sells(max_hold_days=90)
        
    # ── Step 3.6: Scan Bulk & Block Deals ──
    logger.info("Step 3.6: Scanning Bulk & Block Deals...")
    try:
        from src.bulk_deal_monitor import BulkDealMonitor
        bdm = BulkDealMonitor(cache)
        tracked_buys = bdm.scan_today_deals()
        if tracked_buys:
            logger.info(f"  Found {len(tracked_buys)} tracked smart money buys today.")
            for tb in tracked_buys:
                logger.info(f"    {tb['client_name']} bought {tb['scrip_code']}")
    except Exception as e:
        logger.warning(f"Failed to scan bulk deals: {e}")

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

    # ── Step 4.5: Check for L1 Bids (Alternative Data) ──
    logger.info("Step 4.5: Checking eProcure L1 bids (Alternative Data front-running)...")
    from src.eprocure_monitor import EprocureMonitor
    l1_monitor = EprocureMonitor(cache)
    l1_bids = l1_monitor.fetch_l1_bids_for_watchlist()
    
    if l1_bids:
        for bid in l1_bids:
            logger.info(
                f"\n{'=' * 40}\n"
                f"🚨 EARLY ALPHA SIGNAL DETECTED 🚨\n"
                f"L1 Bidder: {bid['contractor_name']} ({bid['scrip_code']})\n"
                f"Tender: {bid['title']}\n"
                f"Amount: Rs. {bid['bid_amount_cr']} Cr\n"
                f"{'=' * 40}"
            )
            # We treat this as an event so the downstream logic alerts on it
            from src.bse_monitor import CorporateEvent
            l1_event = CorporateEvent(
                scrip_code=bid['scrip_code'],
                company_name=bid['contractor_name'],
                title=f"[L1 BID] {bid['title']} (Rs. {bid['bid_amount_cr']} Cr)",
                date=bid['date'],
                category="Alternative Data (L1 Bidder)",
                event_type="contract",
                raw_data={"materiality": {"is_material": True, "materiality_pct": 100, "issuing_authority_state": bid['issuing_authority_state']}}
            )
            contracts.append(l1_event)

    # ── Step 5: Process contract events ──
    alerts_fired = 0

    if contracts:
        logger.info("Step 5: Processing contract events...")
        from src.alpha_engine import AlphaEngine
        alpha_engine = AlphaEngine(cache)
        regime = alpha_engine.get_vix_regime()
        logger.info(f"  VIX Regime: {regime['vix']:.2f} (High Fear: {regime['is_high_fear']})")

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

            # Calculate Conviction Score
            materiality = event.raw_data.get("materiality", {})
            mat_pct = materiality.get("materiality_pct", 0) if materiality else 0
            is_regional_match = materiality.get("is_regional_match", True) if materiality else True
            buyback_mat_pct = 0.0  # Currently we only process contract events here
            
            conviction = alpha_engine.calculate_conviction_score(
                scrip_code=event.scrip_code, 
                materiality_pct=mat_pct,
                is_regional_match=is_regional_match,
                buyback_materiality_pct=buyback_mat_pct,
                vix=regime["vix"]
            )
            c_score = conviction["score"]
            c_breakdown = conviction["breakdown"]
            
            logger.info(f"  Conviction Score: {c_score}/11")
            for b in c_breakdown:
                logger.info(f"    {b}")
                
            # Changed threshold to 4.0 as per Phase 8 (Quarter Kelly minimum)
            if c_score >= 4.0:
                if not dry_run:
                    paper_trader.execute_buy(event.scrip_code, c_score)
                    
                logger.info(f"  🚨 Conviction >= 4.0. ALERTING!")
                
                # Add tender to graph
                tender_id = graph.add_tender(
                    title=event.title,
                    date=event.date,
                    scrip_code=event.scrip_code,
                )
                graph.link_company_to_tender(cin, tender_id)
                
                # Pair Trading (Short Competitors)
                competitors = alpha_engine.find_competitors(company_name=event.company_name, contract_details=event.title)
                
                unconnected_competitors = []
                for comp in competitors:
                    comp_cin = None
                    if comp.get('scrip_code'):
                        c_info = cache.get_company(comp['scrip_code'])
                        if c_info:
                            comp_cin = c_info.get('cin')
                    
                    comp_score = 0
                    if comp_cin:
                        c_connections = graph.alpha_query(comp_cin)
                        if c_connections:
                            comp_score = c_connections[0]["alpha_score"]
                            
                    if comp_score < ALPHA_SCORE_THRESHOLD:
                        unconnected_competitors.append(comp)

                if not dry_run:
                    notifier.send_alpha_alert(
                        connection=top_connection,
                        fundamental=result,
                        announcement={
                            "title": event.title,
                            "date": event.date,
                            "materiality": materiality,
                            "competitors": unconnected_competitors,
                            "conviction": conviction,
                        },
                    )
                    alerts_fired += 1
                else:
                    logger.info("  [DRY RUN] Would have sent alert")
                    alerts_fired += 1
            else:
                logger.info(f"  Conviction Score {c_score} < 2. No alert.")
    else:
        logger.info("Step 5: No contract events to process")

    # ── Step 5.5: Policy Monitoring (V4 Macro Alpha) ──
    logger.info("Step 5.5: Scanning for Macro-Policy Shifts (PIB)...")
    from src.policy_monitor import PolicyMonitor
    from src.alpha_engine import AlphaEngine
    
    alpha_engine = AlphaEngine(cache)
    policy_monitor = PolicyMonitor(cache, alpha_engine)
    policies = policy_monitor.fetch_latest_policies()
    
    if policies:
        for policy in policies:
            impacted_sector = policy["impacted_sector"].lower()
            logger.info(f"  🏛️ Found Policy Tailwind for sector: {impacted_sector}")
            
            # Find watchlist companies matching this niche
            for company in watchlist:
                cin = company.get("cin")
                scrip_code = company.get("scrip_code")
                niche = (company.get("micro_niche") or "").lower()
                
                if not cin or not niche or niche == "unknown":
                    continue
                    
                # Loose keyword matching for sector
                # E.g., if policy says "ethanol blending", it matches niche "ethanol production"
                policy_words = set(impacted_sector.split())
                niche_words = set(niche.split())
                
                # Check intersection or substring
                if policy_words.intersection(niche_words) or impacted_sector in niche or niche in impacted_sector:
                    # Check political connection
                    connections = graph.alpha_query(cin)
                    if connections:
                        top_conn = connections[0]
                        if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                            logger.info(f"  🚨 MACRO POLICY ALPHA DETECTED for {scrip_code} ({company['name']})")
                            if not dry_run:
                                notifier.send_policy_alert(
                                    company=company,
                                    connection=top_conn,
                                    policy=policy
                                )
                                alerts_fired += 1
                            else:
                                logger.info("  [DRY RUN] Would have sent policy alert")

    # ── Step 5.6: Advanced Alpha Scans (V6) ──
    logger.info("Step 5.6: Scanning Advanced Alpha Sources (Tenders, Budgets, Pledges)...")
    
    if not dry_run:
        try:
            logger.info("  -> Running GeM/CPPP Tender Monitor")
            tender_monitor.scan_for_tenders()
            
            logger.info("  -> Running State Budget Monitor")
            state_budget_monitor.scan_budgets()
            
            logger.info("  -> Running Promoter Pledge Monitor")
            pledge_monitor.scan_pledges()
        except Exception as e:
            logger.error(f"  ❌ Error in Advanced Scans: {e}")
    else:
        logger.info("  [DRY RUN] Skipping Advanced Alpha Scans")

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


def run_volume_scan(dry_run: bool = False):
    """
    Phase 3: Smart Money Front-Running
    Runs a daily volume scan on highly connected watchlist companies.
    """
    start_time = datetime.now()
    logger.info("Starting Daily Volume Scan (Phase 3)...")
    
    cache = CacheManager()
    graph = GraphManager(cache)
    screener = FinancialScreener(cache)
    notifier = Notifier(cache)
    from src.volume_tracker import VolumeTracker
    volume_tracker = VolumeTracker(cache)
    
    # 1. Fetch watchlist
    watchlist = cache.get_watchlist()
    scrip_codes = [c["scrip_code"] for c in watchlist if c.get("scrip_code")]
    logger.info(f"Scanning volume for {len(scrip_codes)} companies...")
    
    spikes_found = 0
    
    for company in watchlist:
        cin = company.get("cin")
        scrip_code = company.get("scrip_code")
        company_name = company.get("name")
        nse_symbol = company.get("nse_symbol")
        
        if not cin or not scrip_code:
            continue
            
        # 2. Check graph connections
        connections = graph.alpha_query(cin)
        if not connections:
            continue
            
        top_connection = connections[0]
        score = top_connection["alpha_score"]
        
        # Only track heavily connected companies
        if score >= ALPHA_SCORE_THRESHOLD:
            # 3. Check fundamentals (briefly, to ensure we don't track garbage)
            # Actually, volume tracker just checks yfinance.
            res = volume_tracker.check_volume_spike(scrip_code, company_name, nse_symbol=nse_symbol)
            if res.is_spike:
                spikes_found += 1
                if not dry_run:
                    notifier.send_volume_spike_alert(
                        company_name=company_name,
                        scrip_code=scrip_code,
                        connection=top_connection,
                        z_score=res.z_score,
                        reason=res.reason
                    )
                else:
                    logger.info("  [DRY RUN] Would have sent volume spike alert")
                    
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info(f"VOLUME SCAN COMPLETE — {elapsed:.1f}s elapsed, {spikes_found} spikes found")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Political Alpha Tracker — Daily Pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending alerts or writing to graph",
    )
    parser.add_argument(
        "--scan-volume",
        action="store_true",
        help="Run the Phase 3 Volume Tracker instead of the regular pipeline",
    )
    args = parser.parse_args()

    try:
        if args.scan_volume:
            run_volume_scan(dry_run=args.dry_run)
        else:
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
