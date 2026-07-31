"""
GeM and CPPP Tender Monitor

Scrapes public procurement portals (simulated via an RSS/API structure) to detect 
when a watchlist company wins a government tender *before* the BSE announcement.
"""

import time
import logging
from datetime import datetime
from difflib import SequenceMatcher

from src.cache_manager import CacheManager
from src.notifier import Notifier
from src.graph_manager import GraphManager
from src.config import ALPHA_SCORE_THRESHOLD

logger = logging.getLogger(__name__)

class TenderMonitor:
    def __init__(self, cache: CacheManager, notifier: Notifier, graph: GraphManager):
        self.cache = cache
        self.notifier = notifier
        self.graph = graph

    def _fuzzy_match_company(self, tender_winner_name: str, threshold: float = 0.8) -> dict:
        """
        Fuzzy match the tender winner name against our watchlist companies.
        GeM often lists 'L&T Limited' instead of 'Larsen & Toubro Ltd'.
        """
        best_match = None
        best_score = 0.0
        
        winner_clean = tender_winner_name.lower().replace(" ltd", "").replace(" limited", "").strip()
        
        for company in self.cache.get_watchlist():
            comp_clean = company["name"].lower().replace(" ltd", "").replace(" limited", "").strip()
            score = SequenceMatcher(None, winner_clean, comp_clean).ratio()
            
            if score > best_score:
                best_score = score
                best_match = company
                
        if best_score >= threshold:
            return best_match
        return None

    def _fetch_recent_tenders(self) -> list:
        """
        Simulate fetching from data.gov.in CPPP API or GeM RSS feed.
        In production, this would make an HTTP request to the actual portal.
        """
        # For demonstration purposes, we yield a mock tender that matches a random watchlist company
        watchlist = self.cache.get_watchlist()
        if not watchlist:
            return []
            
        import random
        target = random.choice(watchlist)
        
        niche = target.get('micro_niche')
        if not niche:
            niche = 'Infrastructure'
            
        return [
            {
                "tender_id": f"GEM/2026/B/{random.randint(1000000, 9999999)}",
                "title": f"Construction of {niche.title()} Facility",
                "winner_name": target["name"],  # Exact match for simulation
                "value_cr": round(random.uniform(10.0, 500.0), 2),
                "date": datetime.now().strftime("%Y-%m-%d")
            }
        ]

    def scan_for_tenders(self):
        """Main routine to scan for new tenders and issue alerts."""
        logger.info("Scanning GeM/CPPP for new tender awards...")
        
        recent_tenders = self._fetch_recent_tenders()
        
        for tender in recent_tenders:
            matched_company = self._fuzzy_match_company(tender["winner_name"])
            
            if not matched_company:
                continue
                
            cin = matched_company.get("cin")
            if not cin:
                continue
                
            # Check if this tender is already processed
            with self.cache._connect() as conn:
                exists = conn.execute(
                    "SELECT id FROM tenders WHERE tender_id = ?", 
                    (tender["tender_id"],)
                ).fetchone()
                
            if exists:
                continue
                
            # Save to DB
            with self.cache._connect() as conn:
                conn.execute("""
                    INSERT INTO tenders (tender_id, title, winner_cin, winner_name, value_cr, date, processed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    tender["tender_id"], tender["title"], cin, tender["winner_name"], 
                    tender["value_cr"], tender["date"], datetime.now().isoformat()
                ))
                
            logger.info(f"Matched Tender {tender['tender_id']} to {matched_company['name']}")
            
            # Check Alpha Score
            connections = self.graph.alpha_query(cin)
            if not connections:
                continue
                
            top_conn = connections[0]
            if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                self._send_tender_alert(matched_company, tender, top_conn)

    def _send_tender_alert(self, company: dict, tender: dict, connection: dict):
        """Format and send the Telegram alert for early tender detection."""
        lines = [
            "🚨 <b>PRE-ANNOUNCEMENT TENDER DETECTED (GeM/CPPP)</b> 🚨",
            "",
            f"<b>Company:</b> {company['name']} (BSE: {company['scrip_code']})",
            f"<b>Tender ID:</b> {tender['tender_id']}",
            f"<b>Project:</b> {tender['title']}",
            f"<b>Value:</b> ₹{tender['value_cr']} Cr",
            "",
            "⚠️ <i>This contract was just published on the government portal. It has NOT YET been announced on the BSE. Front-running opportunity.</i>",
            "",
            "🕸️ <b>Political Alpha Link:</b>",
            f"• Score: {connection['alpha_score']:.2f}",
            f"• Director: {connection['director_name']}",
            f"• Donor: {connection['donor_company_name']}"
        ]
        
        if connection.get('is_bureaucrat'):
            lines.append("")
            lines.append("🕴️ <b>DEEP STATE SIGNAL:</b>")
            lines.append(f"<i>{connection['director_name']} is a former high-ranking bureaucrat (IAS/IPS/IRS).</i>")
            
        self.notifier._send_message("\n".join(lines))
