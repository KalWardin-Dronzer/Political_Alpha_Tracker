"""
State Budget NLP Extractor

Monitors State Budgets (via simulated RSS news feeds of state legislative assemblies) 
and uses the Gemini LLM to extract hyper-localized infrastructure and sector allocations.
Matches these allocations to politically connected micro-caps in that state.
"""

import time
import logging
from datetime import datetime
from google import genai
from pydantic import BaseModel

from src.cache_manager import CacheManager
from src.notifier import Notifier
from src.graph_manager import GraphManager
from src.config import GEMINI_API_KEY, ALPHA_SCORE_THRESHOLD

logger = logging.getLogger(__name__)

class SectorAllocation(BaseModel):
    sector: str
    allocation_cr: float
    state: str
    summary: str

class BudgetAnalysis(BaseModel):
    allocations: list[SectorAllocation]

class StateBudgetMonitor:
    def __init__(self, cache: CacheManager, notifier: Notifier, graph: GraphManager):
        self.cache = cache
        self.notifier = notifier
        self.graph = graph
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    def _fetch_recent_state_budgets(self) -> list:
        """
        Simulate fetching the latest State Budget speeches from state portals or news.
        """
        import random
        # Yield a mock budget speech for demonstration
        states = ["Maharashtra", "Bihar", "Uttar Pradesh", "Gujarat"]
        state = random.choice(states)
        return [
            {
                "state": state,
                "title": f"{state} Annual State Budget 2026-27",
                "text": f"The Honorable Finance Minister of {state} presented the budget today. "
                        f"We are allocating ₹5,000 Cr specifically for rural road development and "
                        f"₹2,500 Cr for solar power initiatives across the state.",
                "date": datetime.now().strftime("%Y-%m-%d")
            }
        ]

    def _extract_allocations(self, text: str, state: str) -> list[dict]:
        """Use Gemini to extract sector allocations from the budget speech."""
        prompt = f"""
        You are a financial analyst. Read this state budget excerpt for {state} and extract 
        the specific monetary allocations for different industrial sectors (e.g. Infrastructure, Solar, Roads, Pharma).
        
        Text: {text}
        """
        
        try:
            if not self.client:
                return []
            response = self.client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BudgetAnalysis,
                    temperature=0.1
                )
            )
            import json
            data = json.loads(response.text)
            return data.get("allocations", [])
        except Exception as e:
            logger.error(f"Failed to extract allocations: {e}")
            return []

    def scan_budgets(self):
        """Main routine to scan state budgets."""
        logger.info("Scanning State Budget releases...")
        
        budgets = self._fetch_recent_state_budgets()
        
        for budget in budgets:
            allocations = self._extract_allocations(budget["text"], budget["state"])
            
            for alloc in allocations:
                self._match_and_alert(alloc)
                
    def _match_and_alert(self, alloc: dict):
        """Match the extracted sector allocation to our connected watchlist."""
        # Fuzzy match sector to micro_niche
        watchlist = self.cache.get_watchlist()
        
        for company in watchlist:
            niche = company.get("micro_niche", "").lower()
            sector = alloc['sector'].lower()
            
            # Strict matching: Avoid false positives like matching "development" to pharma.
            if sector in niche or niche in sector:
                cin = company.get("cin")
                if not cin:
                    continue
                    
                connections = self.graph.alpha_query(cin)
                if not connections:
                    continue
                    
                top_conn = connections[0]
                
                # Check if the connection is tied to the state's ruling party
                # In a real app, we'd cross-reference STATE_PARTY_MAPPING
                if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                    self._send_budget_alert(company, alloc, top_conn)

    def _send_budget_alert(self, company: dict, alloc: dict, connection: dict):
        """Send an alert for a favorable state budget allocation."""
        lines = [
            f"🏛️ <b>STATE BUDGET ALPHA DETECTED ({alloc['state']})</b> 🏛️",
            "",
            f"<b>Company:</b> {company['name']} (BSE: {company['scrip_code']})",
            f"<b>Sector:</b> {alloc['sector'].title()}",
            f"<b>Allocation:</b> ₹{alloc['allocation_cr']} Cr",
            f"<b>Details:</b> <i>{alloc['summary']}</i>",
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
