"""
Political Alpha Tracker — Pipeline Orchestrator

Encapsulates the core pipeline logic for scanning BSE, monitoring geopolitical events,
and firing trading signals.
"""

import logging
from datetime import datetime

from src.config import ALPHA_SCORE_THRESHOLD, MCA_CACHE_TTL_DAYS
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
from src.eprocure_monitor import EprocureMonitor
from src.bulk_deal_monitor import BulkDealMonitor
from src.alpha_engine import AlphaEngine
from src.policy_monitor import PolicyMonitor
from src.macro_event_monitor import MacroEventMonitor
from src.volume_tracker import VolumeTracker
from src.technical_analyzer import TechnicalAnalyzer

logger = logging.getLogger("PipelineOrchestrator")

class PipelineOrchestrator:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        
        # Initialize Services
        self.cache = CacheManager()
        self.bse = BSEMonitor(self.cache)
        self.screener = FinancialScreener(self.cache)
        self.mca = MCAResolver(self.cache)
        self.entity = EntityResolver(self.cache)
        self.graph = GraphManager(self.cache)
        self.notifier = Notifier(self.cache)
        self.watchlist_gen = WatchlistGenerator(self.cache)
        self.universe_manager = UniverseManager(self.cache)
        self.tender_monitor = TenderMonitor(self.cache, self.notifier, self.graph)
        self.state_budget_monitor = StateBudgetMonitor(self.cache, self.notifier, self.graph)
        self.pledge_monitor = PledgeMonitor(self.cache, self.notifier, self.graph)
        self.paper_trader = PaperTrader(self.cache)
        self.alpha_engine = AlphaEngine(self.cache)
        self.policy_monitor = PolicyMonitor(self.cache, self.alpha_engine)
        self.macro_monitor = MacroEventMonitor(self.cache, self.alpha_engine)
        self.volume_tracker = VolumeTracker(self.cache)
        self.technical_analyzer = TechnicalAnalyzer(self.cache)
        self.eprocure_monitor = EprocureMonitor(self.cache)
        self.bulk_deal_monitor = BulkDealMonitor(self.cache)
        
        self.alerts_fired = 0
        self.contracts_found = []

    def run_daily_pipeline(self):
        """Execute the full daily pipeline sequence."""
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info(f"DAILY PIPELINE STARTED — {start_time.strftime('%Y-%m-%d %H:%M IST')}")
        logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        logger.info("=" * 60)

        self._step1_poll_telegram()
        scrip_codes = self._step2_build_monitoring_universe()
        
        if not scrip_codes:
            return
            
        events = self._step3_scan_bse_announcements(scrip_codes)
        contracts = [e for e in events if e.event_type == "contract"]
        board_changes = [e for e in events if e.event_type == "board_change"]
        
        logger.info(f"Found {len(contracts)} contract events, {len(board_changes)} board changes")

        self._step3_5_execute_virtual_sells()
        self._step3_6_scan_bulk_deals()
        self._step4_process_board_changes(board_changes)
        
        l1_contracts = self._step4_5_check_l1_bids()
        contracts.extend(l1_contracts)
        self.contracts_found = contracts
        
        self._step5_process_contract_events(contracts)
        self._step5_5_policy_monitoring()
        self._step5_5b_global_macro_events()
        self._step5_6_advanced_scans()
        
        self._step6_wrap_up(start_time, scrip_codes)

    def run_volume_scan(self):
        """Phase 3: Smart Money Front-Running."""
        start_time = datetime.now()
        logger.info("Starting Daily Volume Scan (Phase 3)...")
        
        watchlist = self.cache.get_watchlist()
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
                
            connections = self.graph.alpha_query(cin)
            if not connections:
                continue
                
            top_connection = connections[0]
            score = top_connection["alpha_score"]
            
            if score >= ALPHA_SCORE_THRESHOLD:
                res = self.volume_tracker.check_volume_spike(scrip_code, company_name, nse_symbol=nse_symbol)
                if res.is_spike:
                    spikes_found += 1
                    if not self.dry_run:
                        self.notifier.send_volume_spike_alert(
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

    # ---------------------------------------------------------
    # PRIVATE STEPS
    # ---------------------------------------------------------
    def _step1_poll_telegram(self):
        logger.info("Step 1: Polling Telegram for /exit commands...")
        if not self.dry_run:
            removed = self.notifier.poll_exit_commands()
            if removed:
                logger.info(f"Removed positions: {removed}")
        else:
            logger.info("  [DRY RUN] Skipping Telegram poll")

    def _step2_build_monitoring_universe(self):
        logger.info("Step 2: Building full universe monitoring list...")
        self.universe_manager.update_universe()
        scrip_codes = self.universe_manager.get_full_universe_scrip_codes()

        if not scrip_codes:
            logger.warning("No scrip codes to monitor. Is the universe empty?")
            if not self.dry_run:
                self.notifier.send_system_alert(
                    "Empty Watchlist",
                    "No companies to monitor. Run quarterly refresh.",
                    "WARNING",
                )
        else:
            logger.info(f"Monitoring {len(scrip_codes)} scrip codes")
        return scrip_codes

    def _step3_scan_bse_announcements(self, scrip_codes):
        logger.info("Step 3: Scanning BSE announcements...")
        return self.bse.scan_watchlist(scrip_codes, lookback_days=1)

    def _step3_5_execute_virtual_sells(self):
        if not self.dry_run:
            logger.info("Step 3.5: Checking virtual portfolio for 90-day sells...")
            self.paper_trader.execute_sells(max_hold_days=90)

    def _step3_6_scan_bulk_deals(self):
        logger.info("Step 3.6: Scanning Bulk & Block Deals...")
        try:
            tracked_buys = self.bulk_deal_monitor.scan_today_deals()
            if tracked_buys:
                logger.info(f"  Found {len(tracked_buys)} tracked smart money buys today.")
                for tb in tracked_buys:
                    logger.info(f"    {tb['client_name']} bought {tb['scrip_code']}")
        except Exception as e:
            logger.warning(f"Failed to scan bulk deals: {e}")

    def _step4_process_board_changes(self, board_changes):
        if board_changes:
            logger.info("Step 4: Processing board changes...")
            for event in board_changes:
                company = self.cache.get_company(event.scrip_code)
                if company and company.get("cin"):
                    logger.info(f"  Board change at {event.company_name} — refreshing directors")
                    self.mca.resolve_directors(company["cin"], force_refresh=True)

    def _step4_5_check_l1_bids(self):
        logger.info("Step 4.5: Checking eProcure L1 bids (Alternative Data front-running)...")
        contracts = []
        l1_bids = self.eprocure_monitor.fetch_l1_bids_for_watchlist()
        if l1_bids:
            from src.bse_monitor import CorporateEvent
            for bid in l1_bids:
                logger.info(
                    f"\\n{'=' * 40}\\n"
                    f"🚨 EARLY ALPHA SIGNAL DETECTED 🚨\\n"
                    f"L1 Bidder: {bid['contractor_name']} ({bid['scrip_code']})\\n"
                    f"Tender: {bid['title']}\\n"
                    f"Amount: Rs. {bid['bid_amount_cr']} Cr\\n"
                    f"{'=' * 40}"
                )
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
        return contracts

    def _step5_process_contract_events(self, contracts):
        if not contracts:
            logger.info("Step 5: No contract events to process")
            return

        logger.info("Step 5: Processing contract events...")
        regime = self.alpha_engine.get_vix_regime()
        logger.info(f"  VIX Regime: {regime['vix']:.2f} (High Fear: {regime['is_high_fear']})")

        for event in contracts:
            logger.info(
                f"\\n{'─' * 40}\\n"
                f"Contract: {event.company_name} ({event.scrip_code})\\n"
                f"Title: {event.title}\\n"
                f"Date: {event.date}\\n"
                f"{'─' * 40}"
            )

            result = self.screener.screen(event.scrip_code, event.company_name)
            if not result.passes:
                logger.info(f"  ❌ Failed fundamentals: {result.reason}. Skipping.")
                continue

            logger.info(f"  ✅ Passed fundamentals: {result.summary()}")

            company = self.cache.get_company(event.scrip_code)
            if not company or not company.get("cin"):
                logger.warning(f"  No CIN for {event.scrip_code}. Cannot run Alpha Query.")
                continue

            cin = company["cin"]

            if not self.cache.is_director_cache_fresh(cin, MCA_CACHE_TTL_DAYS):
                logger.info(f"  Refreshing directors for {cin}...")
                self.mca.resolve_directors(cin)

            self.graph.build_from_cache()
            connections = self.graph.alpha_query(cin)

            if not connections:
                logger.info(f"  No political connections found for {cin}")
                continue

            top_connection = connections[0]
            score = top_connection["alpha_score"]
            logger.info(f"  🔗 Top connection: score={score:.2f}, director={top_connection['director_name']}, donor={top_connection['donor_company_name']}")

            materiality = event.raw_data.get("materiality", {})
            mat_pct = materiality.get("materiality_pct", 0) if materiality else 0
            is_regional_match = materiality.get("is_regional_match", True) if materiality else True
            buyback_mat_pct = 0.0
            
            conviction = self.alpha_engine.calculate_conviction_score(
                scrip_code=event.scrip_code, 
                materiality_pct=mat_pct,
                is_regional_match=is_regional_match,
                buyback_materiality_pct=buyback_mat_pct,
                vix=regime["vix"]
            )
            c_score = conviction["score"]
            c_breakdown = conviction["breakdown"]
            
            logger.info(f"  Conviction Score: {c_score}/13.5")
            for b in c_breakdown:
                logger.info(f"    {b}")
            
            # Run standalone Technical Analysis for logging
            ta_result = self.technical_analyzer.analyze(
                scrip_code=event.scrip_code,
                company_name=event.company_name
            )
            logger.info(f"  📊 Technical Analysis: {ta_result.signal} ({ta_result.score}/10)")
            for tb in ta_result.breakdown:
                logger.info(f"    {tb}")
                
            if c_score >= 4.0:
                if not self.dry_run:
                    self.paper_trader.execute_buy(event.scrip_code, c_score)
                    
                logger.info(f"  🚨 Conviction >= 4.0. ALERTING!")
                
                tender_id = self.graph.add_tender(title=event.title, date=event.date, scrip_code=event.scrip_code)
                self.graph.link_company_to_tender(cin, tender_id)
                
                competitors = self.alpha_engine.find_competitors(company_name=event.company_name, contract_details=event.title)
                unconnected_competitors = []
                for comp in competitors:
                    comp_cin = None
                    if comp.get('scrip_code'):
                        c_info = self.cache.get_company(comp['scrip_code'])
                        if c_info:
                            comp_cin = c_info.get('cin')
                    
                    comp_score = 0
                    if comp_cin:
                        c_connections = self.graph.alpha_query(comp_cin)
                        if c_connections:
                            comp_score = c_connections[0]["alpha_score"]
                            
                    if comp_score < ALPHA_SCORE_THRESHOLD:
                        unconnected_competitors.append(comp)

                if not self.dry_run:
                    self.notifier.send_alpha_alert(
                        connection=top_connection,
                        fundamental=result,
                        announcement={
                            "title": event.title,
                            "date": event.date,
                            "materiality": materiality,
                            "competitors": unconnected_competitors,
                            "conviction": conviction,
                            "technical": {
                                "signal": ta_result.signal,
                                "score": ta_result.score,
                                "rsi": ta_result.rsi,
                                "macd_bullish": ta_result.macd_bullish_crossover,
                                "golden_cross": ta_result.is_golden_cross,
                                "obv_up": ta_result.obv_trending_up,
                                "atr_stop": ta_result.atr_stop_loss,
                                "current_price": ta_result.current_price,
                            },
                        },
                    )
                    self.alerts_fired += 1
                else:
                    logger.info("  [DRY RUN] Would have sent alert")
                    self.alerts_fired += 1
            else:
                logger.info(f"  Conviction Score {c_score} < 4. No alert.")

    def _step5_5_policy_monitoring(self):
        logger.info("Step 5.5: Scanning for Macro-Policy Shifts (PIB)...")
        policies = self.policy_monitor.fetch_latest_policies()
        
        if policies:
            watchlist = self.cache.get_watchlist()
            for policy in policies:
                impacted_sector = policy["impacted_sector"].lower()
                logger.info(f"  🏛️ Found Policy Tailwind for sector: {impacted_sector}")
                
                for company in watchlist:
                    cin = company.get("cin")
                    scrip_code = company.get("scrip_code")
                    niche = (company.get("micro_niche") or "").lower()
                    
                    if not cin or not niche or niche == "unknown":
                        continue
                        
                    policy_words = set(impacted_sector.split())
                    niche_words = set(niche.split())
                    
                    if policy_words.intersection(niche_words) or impacted_sector in niche or niche in impacted_sector:
                        connections = self.graph.alpha_query(cin)
                        if connections:
                            top_conn = connections[0]
                            if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                                logger.info(f"  🚨 MACRO POLICY ALPHA DETECTED for {scrip_code} ({company['name']})")
                                if not self.dry_run:
                                    self.notifier.send_policy_alert(
                                        company=company,
                                        connection=top_conn,
                                        policy=policy
                                    )
                                    self.alerts_fired += 1
                                else:
                                    logger.info("  [DRY RUN] Would have sent policy alert")

    def _step5_5b_global_macro_events(self):
        logger.info("Step 5.5b: Scanning for Global Macro-Events...")
        try:
            global_events = self.macro_monitor.fetch_global_events()
            
            if global_events:
                watchlist = self.cache.get_watchlist()
                for event in global_events:
                    event_type = event.get('event_type')
                    logger.info(f"  🌍 Found Global Macro Event: {event_type} - {event.get('catalyst')}")
                    
                    for company in watchlist:
                        cin = company.get("cin")
                        scrip_code = company.get("scrip_code")
                        niche = (company.get("micro_niche") or "unknown").lower()
                        
                        if not cin or niche == "unknown":
                            continue
                            
                        benefits = self.alpha_engine.check_company_macro_benefit(
                            company_name=company.get('name'), 
                            company_niche=niche, 
                            event_summary=event.get('summary')
                        )
                        
                        if benefits:
                            connections = self.graph.alpha_query(cin)
                            if connections:
                                top_conn = connections[0]
                                if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                                    logger.info(f"  🚨 GLOBAL MACRO EVENT ALPHA DETECTED for {scrip_code} ({company['name']})")
                                    if not self.dry_run:
                                        self.notifier.send_macro_event_alert(
                                            company=company,
                                            connection=top_conn,
                                            event=event
                                        )
                                        self.alerts_fired += 1
                                    else:
                                        logger.info("  [DRY RUN] Would have sent macro event alert")
        except Exception as e:
            logger.error(f"  ❌ Error in Macro Event Scans: {e}")

    def _step5_6_advanced_scans(self):
        logger.info("Step 5.6: Scanning Advanced Alpha Sources (Tenders, Budgets, Pledges)...")
        if not self.dry_run:
            try:
                logger.info("  -> Running GeM/CPPP Tender Monitor")
                self.tender_monitor.scan_for_tenders()
                
                logger.info("  -> Running State Budget Monitor")
                self.state_budget_monitor.scan_budgets()
                
                logger.info("  -> Running Promoter Pledge Monitor")
                self.pledge_monitor.scan_pledges()
            except Exception as e:
                logger.error(f"  ❌ Error in Advanced Scans: {e}")
        else:
            logger.info("  [DRY RUN] Skipping Advanced Alpha Scans")

    def _step6_wrap_up(self, start_time, scrip_codes):
        logger.info("Step 6: Saving graph and sending summary...")
        elapsed = (datetime.now() - start_time).total_seconds()

        if not self.dry_run:
            self.graph.save()
            self.notifier.send_daily_summary(
                contracts_found=len(self.contracts_found),
                alerts_fired=self.alerts_fired,
                watchlist_size=len(scrip_codes),
                elapsed_seconds=elapsed,
            )

        logger.info("=" * 60)
        logger.info(
            f"DAILY PIPELINE COMPLETE — "
            f"{elapsed:.1f}s elapsed, "
            f"{len(self.contracts_found)} contracts, "
            f"{self.alerts_fired} alerts"
        )
        logger.info("=" * 60)

        self.cache.log_event(
            "main", "pipeline_complete",
            f"Elapsed: {elapsed:.1f}s, "
            f"Contracts: {len(self.contracts_found)}, Alerts: {self.alerts_fired}"
        )
