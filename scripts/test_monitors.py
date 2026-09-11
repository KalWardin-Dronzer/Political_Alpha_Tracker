import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading")

from src.data.cache_manager import CacheManager
from src.signals.graph_manager import GraphManager
from src.execution.notifier import Notifier
from src.signals.pledge_monitor import PledgeMonitor
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)

def run_tests():
    cache = CacheManager(db_path=Path(r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading\data\cache.sqlite"))
    graph = GraphManager(cache)
    notifier = Notifier(cache)
    

    print("Testing Pledge Monitor...")
    from src.signals.alpha_engine import AlphaEngine
    alpha_engine = AlphaEngine(cache)
    pm = PledgeMonitor(cache, notifier, graph, alpha_engine)
    # pm.scan_pledges() is removed — now uses process_pledge_events(events)
    
    print("Tests complete.")

if __name__ == "__main__":
    run_tests()
