"""
Political Alpha Tracker — Macro Event Monitor

Monitors generic global RSS feeds (Google News World/Business) to extract
major macroeconomic and geopolitical events, dynamically assessing their 
impact on specific Indian corporate micro-niches.
"""

import logging
import feedparser
import time
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class MacroEventMonitor:
    def __init__(self, cache, alpha_engine):
        self.cache = cache
        self.alpha_engine = alpha_engine
        # Using Google News RSS for World and Business
        self.rss_urls = [
            "https://news.google.com/rss/headlines/section/topic/WORLD",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS"
        ]
        
    def fetch_global_events(self) -> List[Dict]:
        """
        Fetches the latest global news and extracts major macro events.
        """
        logger.info(f"Fetching global macro events from Google News RSS...")
        
        events = []
        seen_titles = set()
        
        for rss_url in self.rss_urls:
            try:
                feed = feedparser.parse(rss_url)
            except Exception as e:
                logger.error(f"Failed to parse RSS feed {rss_url}: {e}")
                continue

            if not feed or 'entries' not in feed:
                logger.warning(f"No entries found in RSS feed {rss_url}.")
                continue

            # Process the top 10 most recent global news items
            for entry in feed.entries[:10]:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                published = entry.get('published', '')
                link = entry.get('link', '')
                
                # Check for uniqueness
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                
                # Heuristic to filter for macro events
                keywords = ['war', 'tariffs', 'ban', 'subsidy', 'crisis', 'rate', 'fed', 'rbi', 'inflation', 'conflict', 'pandemic', 'shortage', 'sanctions', 'strike']
                is_relevant = any(k in title.lower() or k in summary.lower() for k in keywords)
                
                if not is_relevant:
                    continue

                text_content = f"Title: {title}\nDate: {published}\nSummary: {summary}\n"
                
                # Zero-Shot Event Extraction via Gemini
                analysis = self.alpha_engine.analyze_macro_event(text_content)
                
                if not analysis:
                    continue
                    
                magnitude = analysis.get("magnitude", "Low")
                if magnitude in ["High", "Medium"]:
                    events.append({
                        "title": title,
                        "date": published,
                        "link": link,
                        "event_type": analysis.get("event_type", "Unknown Macro Event"),
                        "catalyst": analysis.get("catalyst", "Unknown Catalyst"),
                        "impacted_sectors_positive": analysis.get("impacted_sectors_positive", []),
                        "impacted_sectors_negative": analysis.get("impacted_sectors_negative", []),
                        "magnitude": magnitude,
                        "summary": analysis.get("summary", summary)
                    })
                    
                # Rate limit the LLM calls slightly
                time.sleep(1)
                
        logger.info(f"Found {len(events)} major global macro events.")
        return events
