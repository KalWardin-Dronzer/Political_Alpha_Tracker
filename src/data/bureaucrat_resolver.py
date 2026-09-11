"""
Political Alpha Tracker — Bureaucrat Resolver (Phase 5)

Uses LLM (Gemini) to determine if a company director is a former high-ranking 
bureaucrat (IAS, IPS, IRS, IFS, etc.), indicating strong "Deep State" political ties.
"""

import os
import json
import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)

class BureaucratResolver:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            # Use gemini-flash-lite-latest for better world knowledge about Indian bureaucrats
            self.model = genai.GenerativeModel("gemini-flash-lite-latest")
        else:
            logger.warning("GEMINI_API_KEY not found. Bureaucrat resolver disabled.")
            self.model = None

    def check_bureaucrats(self, company_name: str, directors: list[dict]) -> list[dict]:
        """
        Takes a list of directors and uses Gemini to flag bureaucrats.
        Modifies the directors list in-place to add 'is_bureaucrat'.
        Returns the modified list.
        """
        if not self.model or not directors:
            for d in directors:
                d["is_bureaucrat"] = False
            return directors

        director_names = [d.get("name", "") for d in directors if d.get("name")]
        if not director_names:
            return directors

        prompt = (
            f"You are a political intelligence analyst for an Indian hedge fund.\n"
            f"Company: {company_name}\n"
            f"Directors on Board: {', '.join(director_names)}\n\n"
            "Task: Identify if any of these directors are retired high-ranking Indian civil servants. "
            "Specifically look for former IAS (Indian Administrative Service), IPS (Indian Police Service), "
            "IRS (Indian Revenue Service), or IFS officers, or former Secretaries to the Government of India.\n"
            "ONLY flag them as true if you are highly confident based on public knowledge.\n"
            "Return a JSON dictionary mapping the exact director name to a boolean (true if bureaucrat, false otherwise).\n"
            "Do NOT use markdown block wrappers, output raw JSON only."
        )

        try:
            response = self.model.generate_content(prompt)
            res_text = response.text.strip()
            
            if res_text.startswith("```json"):
                res_text = res_text[7:-3].strip()
            elif res_text.startswith("```"):
                res_text = res_text[3:-3].strip()
                
            bureaucrat_map = json.loads(res_text)
            
            for d in directors:
                name = d.get("name", "")
                is_bur = bureaucrat_map.get(name, False)
                # Ensure it's a strict boolean
                d["is_bureaucrat"] = bool(is_bur)
                if is_bur:
                    logger.info(f"🕴️ Deep State Bureaucrat detected: {name} at {company_name}")
                    
        except Exception as e:
            logger.error(f"Failed to resolve bureaucrats for {company_name}: {e}")
            for d in directors:
                d["is_bureaucrat"] = False

        return directors
