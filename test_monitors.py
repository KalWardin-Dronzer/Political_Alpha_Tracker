import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading")

from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from src.notifier import Notifier
from src.tender_monitor import TenderMonitor
from src.state_budget_monitor import StateBudgetMonitor
from src.pledge_monitor import PledgeMonitor
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)

def run_tests():
    cache = CacheManager(db_path=Path(r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading\data\cache.sqlite"))
    graph = GraphManager(cache)
    notifier = Notifier(cache)
    
    print("Testing Tender Monitor...")
    tm = TenderMonitor(cache, notifier, graph)
    tm.scan_for_tenders()
    
    print("Testing State Budget Monitor...")
    sbm = StateBudgetMonitor(cache, notifier, graph)
    sbm.scan_budgets()
    
    print("Testing Pledge Monitor...")
    pm = PledgeMonitor(cache, notifier, graph)
    pm.scan_pledges()
    
    print("Tests complete.")

if __name__ == "__main__":
    run_tests()
