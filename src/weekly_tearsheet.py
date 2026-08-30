import logging
from datetime import datetime, timedelta
from src.cache_manager import CacheManager
from src.graph_manager import GraphManager
from src.notifier import Notifier

logger = logging.getLogger("WeeklyTearsheet")

class WeeklyTearsheet:
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.graph = GraphManager(cache)
        self.notifier = Notifier(cache)
        
    def generate(self) -> str:
        """Generates the weekly tearsheet markdown report."""
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        with self.cache._connect() as conn:
            # 1. Pipeline Stats
            announcements = conn.execute("SELECT count(*) FROM announcements WHERE date >= ?", (seven_days_ago,)).fetchone()[0]
            contracts = conn.execute("SELECT count(*) FROM announcements WHERE is_contract=1 AND date >= ?", (seven_days_ago,)).fetchone()[0]
            
            # 2. Portfolio Stats
            active_positions = conn.execute("SELECT count(*) FROM virtual_portfolio").fetchone()[0]
            invested = conn.execute("SELECT sum(invested_amount) FROM virtual_portfolio").fetchone()[0] or 0.0
            
            trade_hist = conn.execute("SELECT count(*), sum(net_pnl) FROM trade_history WHERE sell_date >= ?", (seven_days_ago,)).fetchone()
            closed_trades = trade_hist[0]
            weekly_pnl = trade_hist[1] or 0.0
            
        report = []
        report.append("📅 **POLITICAL ALPHA - WEEKLY TEARSHEET**")
        report.append(f"*(For the week ending {datetime.now().strftime('%Y-%m-%d')})*")
        report.append("")
        
        report.append("📊 **Pipeline Funnel**")
        report.append(f"- Total Announcements Scanned: {announcements}")
        report.append(f"- Contract Wins Detected: {contracts}")
        report.append("")
        
        report.append("💼 **Portfolio Update**")
        report.append(f"- Active Positions: {active_positions}")
        report.append(f"- Total Invested: ₹{invested:,.2f}")
        report.append(f"- Trades Closed This Week: {closed_trades}")
        report.append(f"- Weekly Realized PnL: ₹{weekly_pnl:,.2f}")
        report.append("")
        
        return "\n".join(report)
        
    def send_to_telegram(self):
        report = self.generate()
        self.notifier.send_system_alert("Weekly Tearsheet", report, level="INFO")
        logger.info("Sent weekly tearsheet to Telegram")

if __name__ == "__main__":
    cache = CacheManager()
    ts = WeeklyTearsheet(cache)
    print(ts.generate())
