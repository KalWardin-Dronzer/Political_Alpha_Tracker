"""
Promoter Pledge Monitor

Monitors BSE SAST (Substantial Acquisition of Shares and Takeovers) and pledge 
disclosures to track when a promoter of a politically connected company 
suddenly releases pledged shares. This is often an insider "tell" that 
a favorable event is imminent.
"""

import time
import logging
from datetime import datetime

from src.cache_manager import CacheManager
from src.notifier import Notifier
from src.graph_manager import GraphManager
from src.config import ALPHA_SCORE_THRESHOLD

logger = logging.getLogger(__name__)

class PledgeMonitor:
    def __init__(self, cache: CacheManager, notifier: Notifier, graph: GraphManager):
        self.cache = cache
        self.notifier = notifier
        self.graph = graph

    def _fetch_recent_pledges(self) -> list:
        """
        Simulate fetching pledge disclosures from BSE API or screener.in.
        """
        watchlist = self.cache.get_watchlist()
        if not watchlist:
            return []
            
        import random
        target = random.choice(watchlist)
        scrip = target["scrip_code"]
        
        # Simulate a sudden release of a huge chunk of shares
        return [
            {
                "scrip_code": scrip,
                "promoter_name": f"{target['name'].split()[0]} Promoter Group",
                "action_type": "Released",
                "pct_change": round(random.uniform(10.0, 45.0), 2),
                "total_pledged_pct": round(random.uniform(0.0, 15.0), 2),
                "date": datetime.now().strftime("%Y-%m-%d")
            }
        ]

    def scan_pledges(self):
        """Main routine to scan pledge changes."""
        logger.info("Scanning for significant Promoter Pledge changes...")
        
        pledges = self._fetch_recent_pledges()
        
        for p in pledges:
            scrip = p["scrip_code"]
            
            # Check if this exact event is already processed for today
            with self.cache._connect() as conn:
                exists = conn.execute(
                    "SELECT id FROM pledges WHERE scrip_code = ? AND date = ? AND action_type = ?", 
                    (scrip, p["date"], p["action_type"])
                ).fetchone()
                
            if exists:
                continue
                
            # Save to DB
            with self.cache._connect() as conn:
                conn.execute("""
                    INSERT INTO pledges (scrip_code, promoter_name, action_type, pct_change, total_pledged_pct, date, processed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    scrip, p["promoter_name"], p["action_type"], p["pct_change"], 
                    p["total_pledged_pct"], p["date"], datetime.now().isoformat()
                ))
                
            # Alpha Engine Check: Is this a politically connected company?
            company = self.cache.get_company(scrip)
            if not company:
                continue
                
            cin = company.get("cin")
            if not cin:
                continue
                
            connections = self.graph.alpha_query(cin)
            if not connections:
                continue
                
            top_conn = connections[0]
            
            # Only alert for "Released" pledges on highly connected companies
            if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD and p["action_type"] == "Released":
                # High conviction threshold: massive sudden release
                if p["pct_change"] > 15.0:
                    self._send_pledge_alert(company, p, top_conn)

    def _send_pledge_alert(self, company: dict, pledge: dict, connection: dict):
        """Send an alert for a sudden promoter pledge release."""
        lines = [
            "💎 <b>INSIDER TELL: PROMOTER PLEDGE RELEASED</b> 💎",
            "",
            f"<b>Company:</b> {company['name']} (BSE: {company['scrip_code']})",
            f"<b>Action:</b> {pledge['promoter_name']} just <b>Released {pledge['pct_change']}%</b> of total equity from pledge.",
            f"<b>Current Pledged:</b> {pledge['total_pledged_pct']}%",
            "",
            "⚠️ <i>A politically-connected promoter suddenly freeing up massive equity is a classic front-running tell before a major contract win or policy shift.</i>",
            "",
            "🕸️ <b>Political Alpha Link:</b>",
            f"• Score: {connection['alpha_score']:.2f}",
            f"• Director: {connection['director_name']}",
            f"• Donor: {connection['donor_company_name']}"
        ]
        
        if connection.get('is_bureaucrat'):
            lines.append("")
            lines.append("🕴️ <b>DEEP STATE SIGNAL:</b>")
            lines.append(f"<i>{connection['director_name']} is a former high-ranking bureaucrat.</i>")
            
        self.notifier._send_message("\n".join(lines))
