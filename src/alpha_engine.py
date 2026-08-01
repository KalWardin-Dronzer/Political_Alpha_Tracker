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
                    model="gemini-2.5-flash", 
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

    def calculate_conviction_score(self, scrip_code: str, materiality_pct: float, sector: str) -> dict:
        """
        Calculates the Conviction Score (0-5) based on multiple Quantamental factors.
        """
        score = 0
        breakdown = []
        
        # 1. Materiality Factor (with Sector Weighting)
        if materiality_pct >= 5.0:
            heavy_sectors = ["defence", "railway", "power", "infrastructure", "construction", "capital goods"]
            sector_lower = sector.lower() if sector else ""
            if any(s in sector_lower for s in heavy_sectors):
                score += 2
                breakdown.append("+2 Materiality (Heavy Industry)")
            else:
                score += 1
                breakdown.append("+1 Materiality")
        
        # 2. Political Connection Factor (Non-connected is better)
        try:
            from src.graph_manager import GraphManager
            graph = GraphManager(self.cache)
            company = self.cache.get_company(scrip_code)
            cin = company.get("cin") if company else None
            is_connected = False
            if cin:
                conns = graph.alpha_query(cin)
                if conns and conns[0]["alpha_score"] > 0:
                    is_connected = True
            
            if not is_connected:
                score += 1
                breakdown.append("+1 Non-Connected (Merit Win)")
            else:
                breakdown.append("0 Connected Firm (High decay risk)")
        except Exception as e:
            logger.warning(f"Failed to check political connection for {scrip_code}: {e}")
            
        # 3. Insider Buying Factor
        try:
            from src.insider_tracker import InsiderTracker
            tracker = InsiderTracker(self.cache)
            cluster = tracker.detect_cluster_buy(scrip_code)
            if cluster:
                score += 1
                breakdown.append("+1 Insider Buying Cluster Detected")
        except Exception as e:
            logger.warning(f"Failed to check insider buying for {scrip_code}: {e}")
            
        # 4. Promoter Pledge Risk
        try:
            with self.cache._connect() as conn:
                # Check for pledges table exists first
                table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pledges'").fetchone()
                if table_exists:
                    pledge = conn.execute(
                        "SELECT total_pledged_pct FROM pledges WHERE scrip_code = ? ORDER BY date DESC LIMIT 1",
                        (scrip_code,)
                    ).fetchone()
                    if pledge:
                        if pledge[0] < 25.0:
                            score += 1
                            breakdown.append(f"+1 Low Pledge Risk ({pledge[0]}%)")
                        else:
                            score -= 1
                            breakdown.append(f"-1 High Pledge Risk ({pledge[0]}%)")
                    else:
                        score += 1
                        breakdown.append("+1 Low Pledge Risk (No pledges found)")
                else:
                    score += 1
                    breakdown.append("+1 Low Pledge Risk (No pledges found)")
        except Exception as e:
            logger.warning(f"Failed to check pledge risk for {scrip_code}: {e}")
            
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
        if not self.model:
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
            response = self.model.generate_content(prompt)
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
        if not self.model:
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
            response = self.model.generate_content(prompt)
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
        if not self.model:
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
            response = self.model.generate_content(prompt)
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
