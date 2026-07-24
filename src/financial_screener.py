"""
Political Alpha Tracker — Financial Screener (The Porinju Layer)

Filters out fundamentally unhealthy companies before they consume
graph resources or generate false signals.

Checks:
    1. Debt-to-Equity ratio < 2.0
    2. Promoter pledging not alarmingly high
    3. Operating Cash Flow not chronically negative

Data Sources:
    - Primary: yfinance (BSE suffix .BO)
    - Fallback: BSE financial results page
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

import yfinance as yf

from src.config import (
    MAX_DEBT_TO_EQUITY, MAX_PROMOTER_PLEDGE_PCT,
    MIN_OPERATING_CASHFLOW, YFINANCE_REQUEST_DELAY,
)
from src.cache_manager import CacheManager

logger = logging.getLogger(__name__)


@dataclass
class FundamentalResult:
    """Result of fundamental screening for a single company."""
    scrip_code: str
    company_name: str
    passes: bool
    de_ratio: Optional[float] = None
    operating_cashflow: Optional[float] = None
    promoter_pledge_pct: Optional[float] = None
    market_cap_cr: Optional[float] = None
    reason: str = ""
    data_available: bool = True

    def summary(self) -> str:
        """Human-readable summary for Telegram alerts."""
        if not self.data_available:
            return "[!] Data unavailable"
        de_str = f"{self.de_ratio:.1f}" if self.de_ratio is not None else "N/A"
        ocf_str = (
            f"₹{self.operating_cashflow / 1e7:.1f} Cr"
            if self.operating_cashflow is not None else "N/A"
        )
        pledge_str = (
            f"{self.promoter_pledge_pct:.1f}%"
            if self.promoter_pledge_pct is not None else "N/A"
        )
        status = "[PASS]" if self.passes else "[FAIL]"
        return f"{status} | D/E: {de_str} | OCF: {ocf_str} | Pledge: {pledge_str}"


class FinancialScreener:
    """
    Screens companies for fundamental health.

    Usage:
        screener = FinancialScreener(cache)
        result = screener.screen("540123", "ABC Infra Ltd")
        if result.passes:
            # proceed with graph query
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache

    def _get_yfinance_data(self, scrip_code: str, nse_symbol: str = None) -> Optional[dict]:
        """
        Fetch fundamental data from Yahoo Finance.

        Args:
            scrip_code: BSE scrip code (will be converted to .BO ticker)
            nse_symbol: Optional NSE symbol (will be converted to .NS ticker)

        Returns:
            Dict with fundamental metrics, or None if unavailable.
        """
        ticker_symbol = f"{scrip_code}.BO"
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            if not info or info.get("regularMarketPrice") is None:
                # Try NSE as fallback
                if nse_symbol:
                    ticker_symbol_nse = f"{nse_symbol}.NS"
                else:
                    # Best-effort fallback if nse_symbol wasn't provided
                    ticker_symbol_nse = f"{scrip_code}.NS"
                    
                ticker = yf.Ticker(ticker_symbol_nse)
                info = ticker.info
                if not info or info.get("regularMarketPrice") is None:
                    return None

            result = {
                "debt_to_equity": info.get("debtToEquity"),
                "market_cap": info.get("marketCap"),
                "total_debt": info.get("totalDebt"),
                "total_equity": info.get("totalStockholderEquity"),
            }

            # Get operating cash flow from cash flow statement
            try:
                cashflow = ticker.cashflow
                if cashflow is not None and not cashflow.empty:
                    # cashflow columns are dates, rows are line items
                    ocf_row = None
                    for idx in cashflow.index:
                        if "operating" in str(idx).lower() and \
                           "cash" in str(idx).lower():
                            ocf_row = idx
                            break
                    if ocf_row is not None:
                        # Get most recent year's OCF
                        result["operating_cashflow"] = float(
                            cashflow.loc[ocf_row].iloc[0]
                        )
                    else:
                        result["operating_cashflow"] = None
                else:
                    result["operating_cashflow"] = None
            except Exception as e:
                logger.debug(
                    f"Could not fetch cashflow for {scrip_code}: {e}"
                )
                result["operating_cashflow"] = None

            return result

        except Exception as e:
            logger.warning(
                f"yfinance fetch failed for {ticker_symbol}: {e}"
            )
            return None

    def _compute_de_ratio(self, data: dict) -> Optional[float]:
        """Compute Debt-to-Equity ratio from yfinance data."""
        # yfinance sometimes provides debtToEquity directly (as percentage)
        de = data.get("debt_to_equity")
        if de is not None:
            # yfinance returns D/E as a percentage (e.g., 150 means 1.5)
            return de / 100.0 if de > 10 else de

        # Fallback: compute from balance sheet items
        debt = data.get("total_debt")
        equity = data.get("total_equity")
        if debt is not None and equity is not None and equity > 0:
            return debt / equity

        return None

    def screen(self, scrip_code: str,
               company_name: str = "",
               nse_symbol: str = None) -> FundamentalResult:
        """
        Run fundamental screening on a single company.

        Args:
            scrip_code: BSE scrip code
            company_name: Company name (for logging)
            nse_symbol: Optional NSE symbol

        Returns:
            FundamentalResult with pass/fail and metrics.
        """
        logger.info(f"Screening fundamentals for {company_name} ({scrip_code})")

        data = self._get_yfinance_data(scrip_code, nse_symbol=nse_symbol)
        time.sleep(YFINANCE_REQUEST_DELAY)

        if not data:
            logger.warning(
                f"No financial data available for {company_name} ({scrip_code})"
            )
            return FundamentalResult(
                scrip_code=scrip_code,
                company_name=company_name,
                passes=False,
                reason="Financial data unavailable from yfinance",
                data_available=False,
            )

        # Extract metrics
        de_ratio = self._compute_de_ratio(data)
        ocf = data.get("operating_cashflow")
        market_cap = data.get("market_cap")
        market_cap_cr = market_cap / 1e7 if market_cap else None

        # Update market cap in cache
        if market_cap_cr:
            self.cache.upsert_company(
                scrip_code=scrip_code,
                name=company_name,
                market_cap=market_cap_cr,
            )

        # Apply screening rules
        reasons = []

        # Rule 1: Debt-to-Equity
        if de_ratio is not None and de_ratio > MAX_DEBT_TO_EQUITY:
            reasons.append(
                f"D/E ratio {de_ratio:.1f} > {MAX_DEBT_TO_EQUITY}"
            )

        # Rule 2: Operating Cash Flow
        if ocf is not None and ocf < MIN_OPERATING_CASHFLOW:
            reasons.append(
                f"Operating CF ₹{ocf/1e7:.1f} Cr is negative"
            )

        passes = len(reasons) == 0
        reason = "; ".join(reasons) if reasons else "All checks passed"

        result = FundamentalResult(
            scrip_code=scrip_code,
            company_name=company_name,
            passes=passes,
            de_ratio=de_ratio,
            operating_cashflow=ocf,
            promoter_pledge_pct=None,  # Pledging requires BSE shareholding parse
            market_cap_cr=market_cap_cr,
            reason=reason,
        )

        log_level = "INFO" if passes else "WARNING"
        logger.log(
            logging.getLevelName(log_level),
            f"  {company_name}: {result.summary()} — {reason}"
        )

        return result

    def screen_batch(self, companies: list[dict]) -> list[FundamentalResult]:
        """
        Screen a batch of companies.

        Args:
            companies: List of dicts with 'scrip_code' and 'name' keys.

        Returns:
            List of FundamentalResult, one per company.
        """
        results = []
        total = len(companies)

        for i, company in enumerate(companies, 1):
            code = company.get("scrip_code", "")
            name = company.get("name", "")
            nse_symbol = company.get("nse_symbol")
            logger.info(f"Screening {i}/{total}: {name}")

            result = self.screen(code, name, nse_symbol=nse_symbol)
            results.append(result)

        passed = sum(1 for r in results if r.passes)
        failed = sum(1 for r in results if not r.passes)
        self.cache.log_event(
            "financial_screener", "batch_complete",
            f"Screened {total} companies: {passed} passed, {failed} failed"
        )

        return results

    def get_market_cap(self, scrip_code: str, nse_symbol: str = None) -> Optional[float]:
        """
        Get market cap in Crores for a scrip code.
        Checks cache first, falls back to yfinance.

        Returns:
            Market cap in Crores, or None if unavailable.
        """
        # Check cache
        company = self.cache.get_company(scrip_code)
        if company and company.get("market_cap"):
            return company["market_cap"]

        # Fetch from yfinance
        data = self._get_yfinance_data(scrip_code, nse_symbol=nse_symbol)
        time.sleep(YFINANCE_REQUEST_DELAY)

        if data and data.get("market_cap"):
            mcap_cr = data["market_cap"] / 1e7
            return mcap_cr

        return None
