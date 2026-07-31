"""
Political Alpha Tracker — Portfolio Manager (Phase 3 V3)

Calculates the mathematically optimal position size using a Fractional 
Kelly Criterion, protecting against catastrophic ruin ("fat tails").
"""

import logging

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
        
        Args:
            win_rate: Historical probability of winning (e.g., 0.60 for 60%)
            avg_win_pct: Historical average return on winning trades (e.g., 0.15 for 15%)
            avg_loss_pct: Historical average return on losing trades (e.g., 0.08 for 8%)
            
        Returns:
            Optimal position size as a percentage of the total portfolio.
        """
        if avg_loss_pct <= 0 or avg_win_pct <= 0:
            return 0.0
            
        # b is the ratio of average win to average loss
        b = avg_win_pct / avg_loss_pct
        
        # Full Kelly: f* = p - (1-p)/b
        # where p is probability of winning
        p = win_rate
        q = 1.0 - p
        
        kelly_pct = p - (q / b)
        
        if kelly_pct <= 0:
            logger.warning(f"Kelly criterion recommends NO BET (Negative expected value). Kelly: {kelly_pct:.2f}")
            return 0.0
            
        # Convert to percentage
        kelly_pct = kelly_pct * 100
        
        # Apply Fractional Kelly (Safety factor)
        fractional_kelly = kelly_pct * self.kelly_fraction
        
        # Apply Max Cap
        final_position_size = min(fractional_kelly, self.max_position_cap)
        
        logger.info(
            f"Position Sizing | "
            f"Win Rate: {p*100:.1f}% | W/L Ratio: {b:.2f} | "
            f"Full Kelly: {kelly_pct:.1f}% | "
            f"Allocating: {final_position_size:.1f}% (Cap: {self.max_position_cap}%)"
        )
        
        return final_position_size
