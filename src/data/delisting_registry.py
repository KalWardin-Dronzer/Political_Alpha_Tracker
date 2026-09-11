"""
Political Alpha Tracker — Delisting Registry (survivorship correction)

THE PROBLEM THIS EXISTS FOR
---------------------------
The price panel is built from the CURRENT company table, so it contains only
companies that still exist. Every company that failed between 2019 and 2026 is
absent by construction — a check of the panel found exactly zero dead price
series out of 1,588 symbols. A backtest over that panel is asking "how did the
survivors do", which is not a question anyone can trade.

NSE publishes the delisted-securities list, and it shows 114 companies delisted
during the panel window, 113 of them missing from the panel. 59 were
liquidations or compulsory delistings — failures where the equity was wiped —
and 51 were voluntary delistings, which are typically buyouts near or above the
market price.

WHAT CAN AND CANNOT BE FIXED
----------------------------
Cannot: reconstruct the missing price history. yfinance purges delisted
tickers — of the 114, only 17 return any data, and most of those are frozen
series that flatline at a last traded price. Free reconstruction is not
available, and inventing plausible paths would be fabricating data.

Can, and this module does:
  1. Keep the real NSE delisting record (symbol, date, type) as project data.
  2. Classify each delisting as a FAILURE or a BUYOUT, because the two have
     opposite consequences for a holder.
  3. Estimate the resulting return drag with stated assumptions, so every
     backtest number can be reported alongside how much it is overstated.
  4. Exclude delisted names from the eligible universe after their delisting
     date, so a future panel containing them cannot trade them posthumously.

A NOTE ON WHAT THIS DOES NOT RESCUE
-----------------------------------
Survivorship bias inflates the factor strategy and the random-selection control
by roughly the same amount, since both draw from the same panel. Correcting it
moves the absolute Sharpe levels down; it does not change the Phase 2 finding
that factor selection performed no better than random. Do not expect this to
revive the factor model.
"""

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DELISTED_FILE = DATA_DIR / "nse_delisted.parquet"

# nsearchives is the host that actually serves this file; www1 fails TLS.
NSE_DELISTED_URL = "https://nsearchives.nseindia.com/content/equities/delisted.xlsx"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# A holder's outcome depends entirely on WHY the listing ended.
FAILURE_KEYWORDS = ("liquidation", "compulsory")


@dataclass
class BiasEstimate:
    """Estimated survivorship drag, with the assumptions that produced it."""
    n_failures: int
    n_buyouts: int
    universe_size: int
    years: float
    annual_failure_rate: float
    annual_drag_pct: float
    assumed_failure_recovery: float
    note: str

    def summary(self) -> dict:
        return {
            "n_failures": self.n_failures,
            "n_buyouts": self.n_buyouts,
            "reconstructed_universe": self.universe_size,
            "window_years": round(self.years, 2),
            "annual_failure_rate_pct": round(self.annual_failure_rate * 100, 3),
            "estimated_annual_drag_pct": round(self.annual_drag_pct * 100, 3),
            "assumed_recovery_on_failure": self.assumed_failure_recovery,
            "note": self.note,
        }


class DelistingRegistry:
    """
        reg = DelistingRegistry()
        reg.refresh()                      # fetch from NSE, cache locally
        reg.delisted_by("2022-01-01")      # symbols already gone by then
        reg.bias_estimate(1588, 2019, 2026)
    """

    def __init__(self, path: Path = DELISTED_FILE):
        self.path = path
        self._df: Optional[pd.DataFrame] = None

    # ──────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────
    def refresh(self, timeout: int = 30) -> int:
        """Download the NSE delisted list and cache it. Returns row count."""
        session = requests.Session()
        session.headers.update(_HEADERS)
        # NSE sets cookies on the landing page; without them the archive 403s.
        try:
            session.get("https://www.nseindia.com", timeout=timeout)
        except Exception:
            pass

        resp = session.get(NSE_DELISTED_URL, timeout=timeout)
        resp.raise_for_status()

        df = pd.read_excel(io.BytesIO(resp.content))
        df.columns = [str(c).strip() for c in df.columns]
        df = df.rename(columns={
            "Symbol": "symbol",
            "Company Name": "name",
            "Board": "board",
            "Delisted Date": "delisted_date",
            "Type of Delisting": "delisting_type",
        })
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        df["delisting_type"] = df["delisting_type"].astype(str).str.strip()
        df["delisted_date"] = pd.to_datetime(df["delisted_date"], errors="coerce")
        df = df.dropna(subset=["symbol", "delisted_date"])
        df["is_failure"] = df["delisting_type"].str.lower().apply(
            lambda t: any(k in t for k in FAILURE_KEYWORDS)
        )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(self.path)
        self._df = df
        logger.info(
            f"Delisting registry refreshed: {len(df)} records, "
            f"{int(df['is_failure'].sum())} failures"
        )
        return len(df)

    def load(self) -> pd.DataFrame:
        if self._df is not None:
            return self._df
        if not self.path.exists():
            logger.warning(
                f"No delisting registry at {self.path}. Call refresh() — until then "
                "backtests are survivorship-biased with no correction available."
            )
            self._df = pd.DataFrame(
                columns=["symbol", "name", "board", "delisted_date",
                         "delisting_type", "is_failure"]
            )
            return self._df
        self._df = pd.read_parquet(self.path)
        return self._df

    # ──────────────────────────────────────────
    # Queries
    # ──────────────────────────────────────────
    def delisted_by(self, as_of) -> set[str]:
        """
        Symbols already delisted at `as_of`.

        Use this to drop names from an eligible universe. A panel that happens
        to contain a delisted symbol must not be allowed to trade it after the
        listing ended — that is look-ahead of the worst kind, since the outcome
        is known.
        """
        df = self.load()
        if df.empty:
            return set()
        ts = pd.Timestamp(as_of)
        return set(df.loc[df["delisted_date"] <= ts, "symbol"])

    def in_window(self, start, end) -> pd.DataFrame:
        df = self.load()
        if df.empty:
            return df
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df["delisted_date"] >= s) & (df["delisted_date"] <= e)]

    # ──────────────────────────────────────────
    # Bias estimate
    # ──────────────────────────────────────────
    def bias_estimate(self, surviving_universe: int, start, end,
                      failure_recovery: float = 0.0) -> BiasEstimate:
        """
        Estimate the annual return drag omitted by a survivors-only panel.

        Method: an equal-weight portfolio drawn from the true universe holds
        eventual failures in proportion to their share of that universe. Each
        failure costs (1 - failure_recovery) of its position. Averaged over the
        window, that is the annual drag a survivors-only backtest never paid.

        `failure_recovery` defaults to 0.0 — liquidation and compulsory
        delisting generally leave common equity with nothing. Voluntary
        delistings are counted separately and assumed value-neutral, since they
        are usually buyouts at or above market.

        THIS IS AN UPPER BOUND FOR A SCREENED STRATEGY. Failures are typically
        illiquid and frozen for months beforehand, so a liquidity floor removes
        many of them before they die. The true drag for a screened universe is
        lower than this figure and cannot be pinned down without the missing
        price history.
        """
        window = self.in_window(start, end)
        n_fail = int(window["is_failure"].sum()) if not window.empty else 0
        n_buy = int((~window["is_failure"]).sum()) if not window.empty else 0

        years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1e-9)
        true_universe = surviving_universe + len(window)

        annual_failure_rate = (n_fail / true_universe / years) if true_universe else 0.0
        annual_drag = annual_failure_rate * (1.0 - failure_recovery)

        return BiasEstimate(
            n_failures=n_fail,
            n_buyouts=n_buy,
            universe_size=true_universe,
            years=years,
            annual_failure_rate=annual_failure_rate,
            annual_drag_pct=annual_drag,
            assumed_failure_recovery=failure_recovery,
            note=("Upper bound for a liquidity-screened strategy: failures are "
                  "usually illiquid and suspended before delisting, so an ADV "
                  "floor excludes many of them in advance."),
        )
