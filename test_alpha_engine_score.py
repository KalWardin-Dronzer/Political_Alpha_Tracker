import logging
import sys

# Configure logging to print to console
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

from src.cache_manager import CacheManager
from src.alpha_engine import AlphaEngine
from src.insider_tracker import InsiderTracker

def test_conviction():
    cache = CacheManager()
    engine = AlphaEngine(cache)
    
    # Try calculating conviction for a known stock
    scrip_code = "532540" # TCS for testing
    
    print("Testing calculate_conviction_score...")
    res = engine.calculate_conviction_score(
        scrip_code=scrip_code,
        materiality_pct=6.5,  # Should give +2.0
        is_regional_match=True,
        buyback_materiality_pct=3.0, # Should give +1.5
        vix=15.0
    )
    
    print(f"Final Score: {res['score']}")
    for b in res['breakdown']:
        print(" ->", b)
        
    assert res['score'] >= 3.5, "Score should be at least 3.5 from Contract Win and Buyback"

if __name__ == "__main__":
    test_conviction()
