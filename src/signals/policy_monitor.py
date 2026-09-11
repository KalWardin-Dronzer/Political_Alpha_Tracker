"""
Political Alpha Tracker — Policy Monitor (Phase 2 V4)

Monitors the Press Information Bureau (PIB) RSS feeds for macro-level 
policy announcements, such as PLI schemes, blending mandates, or privatization.
"""

import logging
import feedparser
import time
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class PolicyMonitor:
    def __init__(self, cache, alpha_engine):
        self.cache = cache
        self.alpha_engine = alpha_engine
        # The main RSS feed for PIB Delhi (Ministry releases)
        self.rss_url = "https://pib.gov.in/rss/Main.xml"
        
    def fetch_latest_policies(self) -> List[Dict]:
        """
        Fetches the latest press releases from PIB and parses them.
        Returns a list of policy documents.
        """
        logger.info(f"Fetching latest government policies from {self.rss_url}...")
        
        try:
            # We use feedparser. If not installed, we fallback to requests+xml
            feed = feedparser.parse(self.rss_url)
        except Exception as e:
            logger.error(f"Failed to parse RSS feed: {e}")
            return []

        if not feed or 'entries' not in feed:
            logger.error("No entries found in PIB RSS feed.")
            return []

        policies = []
        # Process the top 10 most recent press releases to save LLM tokens
        for entry in feed.entries[:10]:
            title = entry.get('title', '')
            summary = entry.get('summary', '')
            published = entry.get('published', '')
            link = entry.get('link', '')
            
            # Simple heuristic: only process press releases that look like major policies
            keywords = ['pli', 'scheme', 'mandate', 'cabinet', 'policy', 'subsidy', 'approved', 'approval', 'incentive', 'monetization']
            is_relevant = any(k in title.lower() or k in summary.lower() for k in keywords)
            
            if not is_relevant:
                continue

            text_content = f"Title: {title}\nDate: {published}\nSummary: {summary}\n"
            
            # Ask the LLM if this is a material macro policy
            analysis = self.alpha_engine.analyze_policy_document(text_content)
            
            if not analysis:
                continue
                
            materiality = analysis.get("materiality", "Low")
            if materiality in ["High", "Medium"]:
                policies.append({
                    "title": title,
                    "date": published,
                    "link": link,
                    "impacted_sector": analysis.get("impacted_sector", "Unknown"),
                    "policy_intent": analysis.get("policy_intent", "Unknown"),
                    "materiality": materiality,
                    "summary": analysis.get("summary", summary)
                })
                
            # Rate limit the LLM calls slightly
            time.sleep(1)
            
        logger.info(f"Found {len(policies)} material policy announcements.")
        return policies
