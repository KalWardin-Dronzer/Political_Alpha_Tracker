"""
Political Alpha Tracker -- Alpha Engine (Phase 1: Materiality)

Processes BSE announcements using LLM (Gemini) to extract the contract value
and calculate the Materiality Threshold (Contract Value / Market Cap).
"""

import os
import re
import json
import logging
from typing import Optional
from google import genai
from pypdf import PdfReader
import yfinance as yf

from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)

class AlphaEngine:
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.api_key = os.getenv("GEMINI_API_KEY")
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not found. Using fallback regex parser.")
            self.client = None

    def get_vix_regime(self) -> dict:
        """Fetch current India VIX to determine if the market is in a high fear regime."""
        try:
            ticker = yf.Ticker("^INDIAVIX")
            hist = ticker.history(period="1d")
            if not hist.empty:
                vix_close = hist["Close"].iloc[-1]
                is_high_fear = vix_close > 22.0
                return {"vix": vix_close, "is_high_fear": is_high_fear}
        except Exception as e:
            logger.warning(f"Failed to fetch India VIX: {e}")
        return {"vix": 15.0, "is_high_fear": False}  # Default safe regime

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from downloaded BSE PDF announcement."""
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages[:3]: # Only read first 3 pages to save tokens
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting PDF {pdf_path}: {e}")
            return ""

    def parse_contract_details(self, text: str) -> dict:
        """
        Uses Gemini LLM to parse the exact Rupee value of the contract and the issuing state.
        Returns a dict: {'contract_value_cr': float, 'issuing_authority_state': str}
        """
        if not text.strip():
            return {"contract_value_cr": None, "issuing_authority_state": "unknown"}

        if self.client:
            prompt = (
                "You are a financial analyst extracting contract details from a stock exchange filing.\n"
                "Read the following text and find two things:\n"
                "1. The total monetary value of the contract/order awarded. Convert the final value to Indian Rupees in Crores (Cr). For example, if it says 'Rs. 1500 Million', output 150. If it says 'Rs 5 Billion', output 500. If not found, use null.\n"
                "2. The issuing authority state (e.g. 'maharashtra', 'telangana', 'central', 'west bengal', 'private'). If it's a central government ministry (NHAI, Railways, Defense), output 'central'. If it's a private company, output 'private'. If a specific Indian state government awarded it, output that state name in lowercase. If you can't tell, output 'unknown'.\n"
                "Return ONLY a JSON object with keys 'contract_value_cr' and 'issuing_authority_state'.\n"
                "Do NOT use markdown block wrappers, output raw JSON only.\n"
                f"TEXT:\n{text[:5000]}"
            )
            try:
                response = self.client.models.generate_content(
                    model="gemini-flash-lite-latest", 
                    contents=prompt
                )
                res_text = response.text.strip()
                if res_text.startswith("```json"):
                    res_text = res_text[7:-3].strip()
                elif res_text.startswith("```"):
                    res_text = res_text[3:-3].strip()
                    
                data = json.loads(res_text)
                return {
                    "contract_value_cr": data.get("contract_value_cr"),
                    "issuing_authority_state": data.get("issuing_authority_state", "unknown").lower()
                }
            except Exception as e:
                logger.error(f"Gemini parsing failed: {e}")
                # Fallback to regex
                return self._fallback_parse_details(text)
        else:
            return self._fallback_parse_details(text)

    def _fallback_parse_details(self, text: str) -> dict:
        """Simple regex heuristic to find 'Rs X Cr' if LLM is unavailable."""
        result = {"contract_value_cr": None, "issuing_authority_state": "unknown"}
        
        # 1. Parse value
        pattern = re.compile(r"(?i)(?:rs\.?|inr|₹)\s*([\d,.]+)\s*(cr|crore|million|billion)?")
        matches = pattern.findall(text)
        if matches:
            try:
                val_str, unit = matches[0]
                val = float(val_str.replace(",", ""))
                unit = unit.lower() if unit else ""
                
                if "million" in unit:
                    val = val / 10
                elif "billion" in unit:
                    val = val * 100
                elif not unit:
                    val = val / 10000000
                    
                result["contract_value_cr"] = val
            except Exception:
                pass
                
        # 2. Naive state parser
        text_lower = text.lower()
        states = ["maharashtra", "telangana", "karnataka", "tamil nadu", "west bengal", "odisha", "andhra pradesh", "bihar"]
        for s in states:
            if s in text_lower:
                result["issuing_authority_state"] = s
                break
        else:
            if any(x in text_lower for x in ["nhai", "railway", "defense", "ministry", "central"]):
                result["issuing_authority_state"] = "central"
                
        return result

    def evaluate_materiality(self, announcement_id: int, pdf_path: str, scrip_code: str, recipient_party: str = None) -> dict:
        """
        Evaluate if a newly downloaded contract announcement is mathematically material
        and optionally check regional matching if a recipient party is provided.
        Returns a dict with materiality details.
        """
        text = self.extract_text_from_pdf(pdf_path)
        details = self.parse_contract_details(text)
        contract_value_cr = details.get("contract_value_cr")
        issuing_state = details.get("issuing_authority_state")
        
        if contract_value_cr is None:
            return {"is_material": False, "reason": "Could not extract contract value"}

        # Update database with contract value and issuing state
        with self.cache._connect() as conn:
            conn.execute(
                "UPDATE announcements SET contract_value_cr = ?, issuing_authority_state = ? WHERE id = ?",
                (contract_value_cr, issuing_state, announcement_id)
            )

        # Get company market cap
        company = self.cache.get_company(scrip_code)
        if not company or not company.get("market_cap"):
            return {"is_material": False, "reason": "Market cap unknown"}

        market_cap_cr = company["market_cap"]
        materiality_pct = (contract_value_cr / market_cap_cr) * 100

        is_material = materiality_pct >= 5.0
        
        # Check Regional Match (Phase 2)
        is_regional_match = True
        regional_reason = "Match (No party specified)"
        if recipient_party and issuing_state and issuing_state != "unknown":
            from src.config import STATE_PARTY_MAPPING
            expected_parties = STATE_PARTY_MAPPING.get(issuing_state, [])
            party_lower = recipient_party.lower()
            
            if expected_parties:
                is_regional_match = any(ep in party_lower for ep in expected_parties)
                if not is_regional_match:
                    regional_reason = f"Mismatch: {issuing_state.title()} contract but party is {recipient_party}"
                else:
                    regional_reason = f"Match: {issuing_state.title()} contract mapped to {recipient_party}"
            else:
                regional_reason = f"No party mapping defined for state {issuing_state}"

        return {
            "is_material": is_material,
            "contract_value_cr": contract_value_cr,
            "issuing_authority_state": issuing_state,
            "is_regional_match": is_regional_match,
            "regional_reason": regional_reason,
            "market_cap_cr": market_cap_cr,
            "materiality_pct": materiality_pct,
            "reason": f"Contract value is {materiality_pct:.2f}% of Market Cap"
        }

    def calculate_conviction_score(self, scrip_code: str, materiality_pct: float = 0.0, 
                                   is_regional_match: bool = True, buyback_materiality_pct: float = 0.0,
                                   vix: float = 15.0, event_date: str = None) -> dict:
        """
        Calculates the Conviction Score (0-11) based on Phase 8 Quantamental factors.
        Applies Hard Filters before scoring.
        """
        breakdown = []
        
        # --- HARD FILTERS (If any fail, return score 0 immediately) ---
        if not is_regional_match:
            return {"score": 0.0, "breakdown": ["FAILED HARD FILTER: Regional Party Mismatch"]}
            
        if vix > 22.0:
            return {"score": 0.0, "breakdown": [f"FAILED HARD FILTER: Market VIX Too High ({vix:.2f})"]}
            
        try:
            with self.cache._connect() as conn:
                table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pledges'").fetchone()
                if table_exists:
                    pledge = conn.execute(
                        "SELECT total_pledged_pct FROM pledges WHERE scrip_code = ? ORDER BY date DESC LIMIT 1",
                        (scrip_code,)
                    ).fetchone()
                    if pledge and pledge[0] >= 25.0:
                        return {"score": 0.0, "breakdown": [f"FAILED HARD FILTER: Promoter Pledge High ({pledge[0]}%)"]}
        except Exception as e:
            logger.warning(f"Failed to check pledge risk for {scrip_code}: {e}")
            
        # --- SCORING ---
        score = 0.0
        
        # 1. Contract Win (Materiality)
        if materiality_pct >= 5.0:
            score += 2.0
            breakdown.append(f"+2.0 Contract Win Materiality ({materiality_pct:.1f}%)")
            
        # 2. Corporate Buyback
        if buyback_materiality_pct >= 2.0:
            score += 1.5
            breakdown.append(f"+1.5 Corporate Buyback ({buyback_materiality_pct:.1f}%)")
            
        # 3. Political Connection
        try:
            from src.graph_manager import GraphManager
            graph = GraphManager(self.cache)
            company = self.cache.get_company(scrip_code)
            cin = company.get("cin") if company else None
            if cin:
                conns = graph.alpha_query(cin)
                if conns and conns[0]["alpha_score"] > 0:
                    score += 0.5
                    breakdown.append("+0.5 Political Network Connection")
        except Exception as e:
            logger.warning(f"Failed to check political connection for {scrip_code}: {e}")
            
        # 4 & 5. Insider Buying & SAST External Acquirer
        try:
            from src.insider_tracker import InsiderTracker
            tracker = InsiderTracker(self.cache)
            cluster = tracker.detect_cluster_buy(scrip_code)
            if cluster:
                score += 2.0
                breakdown.append("+2.0 Insider Buying Cluster")
                
            if tracker.detect_sast_external_acquirer(scrip_code):
                score += 2.0
                breakdown.append("+2.0 SAST External Acquirer (Hostile / Whale Entry)")
        except Exception as e:
            logger.warning(f"Failed to check insider buying for {scrip_code}: {e}")
            
        # 6. Bulk/Block Deal (Smart Money)
        try:
            from src.bulk_deal_monitor import BulkDealMonitor
            bdm = BulkDealMonitor(self.cache)
            if bdm.has_recent_tracked_buy(scrip_code):
                score += 1.5
                breakdown.append("+1.5 Smart Money Bulk/Block Deal")
        except Exception as e:
            logger.warning(f"Failed to check bulk deals for {scrip_code}: {e}")
            
        # 7. Superstar New Entry
        try:
            from src.superstar_tracker import SuperstarTracker
            sst = SuperstarTracker(self.cache)
            if sst.check_superstar_entry(scrip_code):
                score += 1.0
                breakdown.append("+1.0 Superstar New Entry")
        except Exception as e:
            logger.warning(f"Failed to check superstar tracker for {scrip_code}: {e}")
            
        # 8. Technical Analysis (Entry Timing)
        try:
            from src.technical_analyzer import TechnicalAnalyzer
            ta = TechnicalAnalyzer(self.cache)
            ta_result = ta.analyze(scrip_code, end_date=event_date)
            adj = ta_result.conviction_adjustment
            if adj != 0:
                sign = "+" if adj > 0 else ""
                score += adj
                breakdown.append(f"{sign}{adj:.1f} Technical Analysis: {ta_result.signal} ({ta_result.score}/10)")
        except Exception as e:
            logger.warning(f"Failed to check technical analysis for {scrip_code}: {e}")
            
        return {
            "score": score,
            "breakdown": breakdown
        }

    def find_competitors(self, company_name: str, contract_details: str = "") -> list[dict]:
        """
        Uses Gemini LLM to identify top publicly listed Indian competitors
        for pair trading (shorting the losers).
        Returns a list of dicts: [{'name': 'Competitor A', 'scrip_code': '123456', 'reason': '...'}, ...]
        """
        if not self.client:
            return []
            
        prompt = (
            f"You are a hedge fund analyst. The Indian company '{company_name}' just won a major contract.\n"
            f"Context: {contract_details}\n"
            "Identify 2-3 of their primary publicly listed Indian competitors who likely lost out on this market share. "
            "For each competitor, provide their name, their 6-digit BSE scrip code (if known, otherwise leave empty), and a brief 1-sentence reason why they are a direct competitor.\n"
            "Return ONLY a JSON list of objects with keys: 'name', 'scrip_code', and 'reason'.\n"
            "Do NOT use markdown block wrappers, output raw JSON only."
        )
        
        try:
            response = self.client.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
            res_text = response.text.strip()
            if res_text.startswith("```json"):
                res_text = res_text[7:-3].strip()
            elif res_text.startswith("```"):
                res_text = res_text[3:-3].strip()
                
            data = json.loads(res_text)
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            logger.error(f"Gemini competitor extraction failed: {e}")
            return []

    def tag_company_niche(self, company_name: str, sector: str, industry: str) -> str:
        """
        Uses Gemini LLM to generate a specific 'micro-niche' for a company,
        enabling precise macro-policy matching.
        """
        if not self.client:
            return industry or "unknown"

        prompt = (
            f"You are a hedge fund analyst profiling Indian micro-cap companies.\n"
            f"Company: {company_name}\n"
            f"Broad Sector: {sector}\n"
            f"Broad Industry: {industry}\n"
            "Identify the highly specific 'micro-niche' this company operates in. "
            "For example, instead of 'Energy', output 'Ethanol Blending'. Instead of 'Industrials', output 'Drone Manufacturing'. "
            "Return ONLY a raw string (2-4 words max). No JSON, no markdown, no quotes."
        )

        try:
            response = self.client.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
            niche = response.text.strip().replace('"', '').replace("'", "")
            return niche
        except Exception as e:
            logger.error(f"Gemini niche tagging failed for {company_name}: {e}")
            return industry or "unknown"

    def analyze_policy_document(self, text: str) -> dict:
        """
        Uses Gemini LLM to parse a government press release (PIB/Gazette) 
        and extract the impacted sector, policy intent, and materiality.
        """
        if not self.client:
            return {}

        prompt = (
            "You are a hedge fund analyst identifying Macro-Policy Alpha.\n"
            "Read the following government press release/policy notification and extract the key economic tailwinds.\n"
            "Return a JSON object with the following keys:\n"
            "- 'impacted_sector': The specific niche industry benefiting (e.g., 'Ethanol Production', 'Airport Management', 'Drone Manufacturing'). Keep it brief (2-4 words).\n"
            "- 'policy_intent': What is the policy doing? (e.g., 'Production Linked Incentive (PLI)', 'Import Ban', 'Privatization', 'Subsidies').\n"
            "- 'materiality': How large is the economic impact on the sector? Choose 'High', 'Medium', or 'Low'.\n"
            "- 'summary': A 1-sentence summary of the tailwind.\n"
            "Return ONLY raw JSON without markdown wrappers.\n"
            f"TEXT:\n{text[:6000]}"
        )

        try:
            response = self.client.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
            res_text = response.text.strip()
            if res_text.startswith("```json"):
                res_text = res_text[7:-3].strip()
            elif res_text.startswith("```"):
                res_text = res_text[3:-3].strip()

            data = json.loads(res_text)
            return data
        except Exception as e:
            logger.error(f"Gemini policy analysis failed: {e}")
            return {}

    def analyze_macro_event(self, text: str) -> dict:
        """
        Uses Gemini LLM to parse a generic macro-economic or geopolitical news event
        and extract structural details.
        """
        if not self.client:
            return {}

        prompt = (
            "You are a hedge fund analyst identifying Macro-Event Alpha.\n"
            "Read the following global news/macro event and extract the key economic tailwinds and headwinds.\n"
            "Return a JSON object with the following keys:\n"
            "- 'event_type': The category of event (e.g., 'Geopolitical Conflict', 'Trade War', 'Pandemic', 'Monetary Policy').\n"
            "- 'catalyst': A brief 2-5 word description of the specific catalyst.\n"
            "- 'impacted_sectors_positive': An array of strings representing the specific micro-niche sectors that benefit.\n"
            "- 'impacted_sectors_negative': An array of strings representing the specific micro-niche sectors that suffer.\n"
            "- 'magnitude': How large is the economic impact? Choose 'High', 'Medium', or 'Low'.\n"
            "- 'summary': A 1-sentence summary of the catalyst.\n"
            "Return ONLY raw JSON without markdown wrappers.\n"
            f"TEXT:\n{text[:6000]}"
        )

        try:
            response = self.client.models.generate_content(model='gemini-flash-lite-latest', contents=prompt)
            res_text = response.text.strip()
            if res_text.startswith("```json"):
                res_text = res_text[7:-3].strip()
            elif res_text.startswith("```"):
                res_text = res_text[3:-3].strip()

            data = json.loads(res_text)
            return data
        except Exception as e:
            logger.error(f"Gemini macro event analysis failed: {e}")
            return {}

    def check_company_macro_benefit(self, company_name: str, company_niche: str, event_summary: str) -> bool:
        """
        Directly queries the LLM to determine if a specific company benefits from a macro event.
        Returns True if it's a clear beneficiary.
        """
        if not self.client:
            return False

        prompt = (
            "You are a hedge fund analyst.\n"
            f"A major macro event has occurred: {event_summary}\n"
            f"We are evaluating a company named '{company_name}' operating in the niche: '{company_niche}'.\n"
            "Does this company directly and clearly benefit economically from this macro event? "
            "Answer ONLY with a boolean 'true' or 'false'. Return raw JSON.\n"
            "Example output:\n"
            "true"
        )
        
        try:
            response = self.client.models.generate_content(model='gemini-flash-lite-latest', contents=prompt)
            res_text = response.text.strip().lower()
            return 'true' in res_text
        except Exception as e:
            logger.error(f"Gemini company benefit check failed: {e}")
            return False
