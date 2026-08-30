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
from src.alpha_engine import AlphaEngine
from src.config import ALPHA_SCORE_THRESHOLD

logger = logging.getLogger(__name__)

class PledgeMonitor:
    def __init__(self, cache: CacheManager, notifier: Notifier, graph: GraphManager, alpha_engine: AlphaEngine):
        self.cache = cache
        self.notifier = notifier
        self.graph = graph
        self.alpha_engine = alpha_engine

    def process_pledge_events(self, events: list):
        """Main routine to process pledge events detected by BSE Monitor."""
        logger.info(f"Processing {len(events)} Promoter Pledge events...")
        
        for e in events:
            scrip = e.scrip_code
            date = e.date
            
            # Extract PDF or text
            pdf_path = e.raw_data.get('pdf_path')
            
            if pdf_path:
                text = self.alpha_engine.extract_text_from_pdf(pdf_path)
            else:
                text = e.title
                
            if not text:
                continue

            analysis = self.alpha_engine.analyze_pledge_document(text)
            
            if not analysis:
                continue

            action_type = analysis.get("action_type")
            if action_type not in ["Created", "Released", "Invoked"]:
                continue
                
            pct_change = analysis.get("pct_change", 0.0)
            total_pledged_pct = analysis.get("total_pledged_pct", 0.0)
            promoter_name = analysis.get("promoter_name", "Promoter Group")

            # Check if this exact event is already processed for today
            with self.cache._connect() as conn:
                exists = conn.execute(
                    "SELECT id FROM pledges WHERE scrip_code = ? AND date = ? AND action_type = ?", 
                    (scrip, date, action_type)
                ).fetchone()
                
            if exists:
                continue
                
            # Save to DB
            try:
                with self.cache._connect() as conn:
                    conn.execute("""
                        INSERT INTO pledges (scrip_code, promoter_name, action_type, pct_change, total_pledged_pct, date, processed, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """, (
                        scrip, promoter_name, action_type, pct_change, 
                        total_pledged_pct, date, datetime.now().isoformat()
                    ))
            except Exception as db_e:
                logger.warning(f"Could not save pledge to db, maybe table missing? Error: {db_e}")
                
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
            if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD and action_type == "Released":
                # High conviction threshold: meaningful release
                if pct_change >= 2.0:
                    pledge_data = {
                        "promoter_name": promoter_name,
                        "pct_change": pct_change,
                        "total_pledged_pct": total_pledged_pct
                    }
                    self._send_pledge_alert(company, pledge_data, top_conn)

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
