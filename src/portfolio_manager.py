import logging
from datetime import datetime, timedelta
import yfinance as yf
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)

class PortfolioManager:
    def __init__(self, max_position_cap_pct: float = 5.0, kelly_fraction: float = 0.5):
        """
        Args:
            max_position_cap_pct: The absolute maximum % of portfolio to risk on a single trade.
            kelly_fraction: The fraction of the Kelly bet to take (e.g., 0.5 for Half-Kelly).
        """
        self.max_position_cap = max_position_cap_pct
        self.kelly_fraction = kelly_fraction
        
    def calculate_position_size(self, win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        """
        Calculates the optimal position size using the Kelly Criterion.
        """
        if avg_loss_pct <= 0 or avg_win_pct <= 0:
            return 0.0
            
        b = avg_win_pct / avg_loss_pct
        p = win_rate
        q = 1.0 - p
        kelly_pct = p - (q / b)
        
        if kelly_pct <= 0:
            logger.warning(f"Kelly criterion recommends NO BET (Negative expected value). Kelly: {kelly_pct:.2f}")
            return 0.0
            
        kelly_pct = kelly_pct * 100
        fractional_kelly = kelly_pct * self.kelly_fraction
        final_position_size = min(fractional_kelly, self.max_position_cap)
        
        logger.info(
            f"Position Sizing | Win Rate: {p*100:.1f}% | W/L Ratio: {b:.2f} | "
            f"Full Kelly: {kelly_pct:.1f}% | Allocating: {final_position_size:.1f}%"
        )
        return final_position_size

class PaperTrader:
    def __init__(self, cache: CacheManager, initial_capital: float = 100000.0):
        self.cache = cache
        self.initial_capital = initial_capital
        
        # Indian Equity Delivery Charges (Zerodha Pricing)
        self.brokerage = 0.0
        self.stt_rate = 0.001  # 0.1% on Buy and Sell
        self.txn_charge_rate = 0.0000325  # NSE Transaction charge 0.00325%
        self.sebi_rate = 0.000001  # ₹10 per crore
        self.stamp_duty_rate = 0.00015  # 0.015% on BUY only
        self.gst_rate = 0.18  # 18% on (brokerage + txn + sebi)
        self.dp_charge = 15.93  # Flat DP charge per sell transaction per day

        # Slippage penalty (e.g. 0.5% worse price due to illiquidity)
        self.slippage_pct = 0.005
        
    def _get_live_price(self, scrip_code: str) -> float:
        """Fetch real-time closing/last price from Yahoo Finance."""
        try:
            # Look up NSE symbol from DB for reliable data
            company = self.cache.get_company(scrip_code)
            nse_symbol = company.get("nse_symbol") if company else None
            
            # Try NSE first (more reliable on Yahoo Finance)
            if nse_symbol:
                ticker = yf.Ticker(f"{nse_symbol}.NS")
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return hist["Close"].iloc[-1]
            
            # Fallback to BSE
            ticker = yf.Ticker(f"{scrip_code}.BO")
            hist = ticker.history(period="1d")
            if not hist.empty:
                return hist["Close"].iloc[-1]
            
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch price for {scrip_code}: {e}")
            return 0.0

    def get_available_capital(self) -> float:
        """Calculate uninvested cash."""
        with self.cache._connect() as conn:
            invested = conn.execute("SELECT sum(invested_amount) FROM virtual_portfolio").fetchone()[0] or 0.0
            realized_pnl = conn.execute("SELECT sum(net_pnl) FROM trade_history").fetchone()[0] or 0.0
            return self.initial_capital + realized_pnl - invested

    def _calculate_buy_costs(self, raw_price: float, quantity: int):
        execution_price = raw_price * (1 + self.slippage_pct)
        turnover = execution_price * quantity
        stt = round(turnover * self.stt_rate, 2)
        txn_charges = round(turnover * self.txn_charge_rate, 2)
        sebi = round(turnover * self.sebi_rate, 2)
        stamp_duty = round(turnover * self.stamp_duty_rate, 2)
        gst = round((self.brokerage + txn_charges + sebi) * self.gst_rate, 2)
        
        total_costs = stt + txn_charges + sebi + stamp_duty + gst
        return execution_price, turnover, total_costs, stt, stamp_duty, txn_charges

    def _calculate_sell_costs(self, raw_price: float, quantity: int):
        execution_price = raw_price * (1 - self.slippage_pct)
        turnover = execution_price * quantity
        stt = round(turnover * self.stt_rate, 2)
        txn_charges = round(turnover * self.txn_charge_rate, 2)
        sebi = round(turnover * self.sebi_rate, 2)
        gst = round((self.brokerage + txn_charges + sebi) * self.gst_rate, 2)
        
        total_costs = stt + txn_charges + sebi + gst + self.dp_charge
        return execution_price, turnover, total_costs, stt, txn_charges

    def execute_buy(self, scrip_code: str, conviction_score: float):
        """Simulate buying a stock based on Conviction Kelly-Sizing."""
        with self.cache._connect() as conn:
            existing = conn.execute("SELECT quantity FROM virtual_portfolio WHERE scrip_code = ?", (scrip_code,)).fetchone()
            if existing:
                logger.info(f"Skipping buy: {scrip_code} is already in portfolio.")
                return False

        available_cash = self.get_available_capital()
        
        # Position Sizing Logic (Kelly Tiers based on Phase 8)
        if conviction_score >= 8.0:
            allocation_pct = 0.25  # Full Kelly cap
        elif conviction_score >= 6.0:
            allocation_pct = 0.15  # Half Kelly cap
        elif conviction_score >= 4.0:
            allocation_pct = 0.05  # Quarter Kelly cap
        else:
            return False
            
        target_allocation = available_cash * allocation_pct
        if target_allocation < 1000:
            logger.warning(f"Insufficient funds to buy {scrip_code}")
            return False
            
        raw_price = self._get_live_price(scrip_code)
        if raw_price <= 0:
            return False
            
        estimated_exec_price = raw_price * (1 + self.slippage_pct)
        quantity = int((target_allocation * 0.99) / estimated_exec_price)
        
        if quantity == 0:
            return False
            
        exec_price, turnover, total_costs, stt, stamp_duty, txn_charges = self._calculate_buy_costs(raw_price, quantity)
        total_outflow = turnover + total_costs
        
        if total_outflow > available_cash:
            logger.warning("Target allocation exceeds available cash after exact tax calculation.")
            return False

        today_str = datetime.now().strftime("%Y-%m-%d")
        
        with self.cache._connect() as conn:
            conn.execute("""
                INSERT INTO virtual_portfolio (scrip_code, buy_date, buy_price, quantity, invested_amount, conviction_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (scrip_code, today_str, exec_price, quantity, total_outflow, conviction_score))
            
        logger.info(f"✅ PAPER BUY: {quantity} shares of {scrip_code} at ₹{exec_price:.2f}. Capital Invested: ₹{total_outflow:.2f}. Total Taxes/Fees: ₹{total_costs:.2f}")
        return True

    def execute_sells(self, max_hold_days: int = 90):
        """Review portfolio and sell anything older than max_hold_days."""
        today = datetime.now()
        
        with self.cache._connect() as conn:
            positions = conn.execute("SELECT scrip_code, buy_date, buy_price, quantity, invested_amount FROM virtual_portfolio").fetchall()
            
        for pos in positions:
            scrip_code, buy_date_str, buy_price, quantity, invested_amount = pos
            buy_date = datetime.strptime(buy_date_str, "%Y-%m-%d")
            
            days_held = (today - buy_date).days
            if days_held >= max_hold_days:
                self.sell_position(scrip_code, buy_date_str, buy_price, quantity, invested_amount)

    def sell_position(self, scrip_code: str, buy_date: str, buy_price: float, quantity: int, invested_amount: float):
        """Sell a specific position."""
        raw_price = self._get_live_price(scrip_code)
        if raw_price <= 0:
            logger.error(f"Cannot sell {scrip_code}: price fetch failed.")
            return False
            
        exec_price, turnover, total_costs, stt, txn_charges = self._calculate_sell_costs(raw_price, quantity)
        net_inflow = turnover - total_costs
        
        net_pnl = net_inflow - invested_amount
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        with self.cache._connect() as conn:
            conn.execute("DELETE FROM virtual_portfolio WHERE scrip_code = ?", (scrip_code,))
            conn.execute("""
                INSERT INTO trade_history (scrip_code, buy_date, sell_date, buy_price, sell_price, quantity, stt, stamp_duty, txn_charges, dp_charges, net_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (scrip_code, buy_date, today_str, buy_price, exec_price, quantity, stt, 0.0, txn_charges, self.dp_charge, net_pnl))
            
        logger.info(f"🔴 PAPER SELL: {quantity} shares of {scrip_code} at ₹{exec_price:.2f}. Realized P&L: ₹{net_pnl:.2f}. Total Taxes/Fees: ₹{total_costs:.2f}")
        return True
