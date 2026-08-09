from src.cache_manager import CacheManager
from src.alpha_engine import AlphaEngine
from src.macro_event_monitor import MacroEventMonitor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test")

cache = CacheManager()
alpha = AlphaEngine(cache)
monitor = MacroEventMonitor(cache, alpha)

logger.info("Testing fetch_global_events()...")
events = monitor.fetch_global_events()

for e in events:
    logger.info(f"Event: {e['event_type']} - {e['catalyst']} (Magnitude: {e['magnitude']})")
    
if events:
    # Test checking benefit against a dummy company
    res = alpha.check_company_macro_benefit("Tata Advanced Systems", "Defense Manufacturing", events[0]['summary'])
    logger.info(f"Does Tata Defense benefit from {events[0]['catalyst']}? -> {res}")
else:
    logger.info("No macro events found today.")
