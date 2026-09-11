"""
Political Alpha Tracker — Price Store (Phase 1)

A local, adjusted daily price panel for the cross-sectional factor engine.

WHY THIS EXISTS
---------------
The event-driven pipeline only ever needed prices for one scrip at a time, so
it fetched them on demand. A cross-sectional factor strategy needs the whole
universe aligned on a common date index at every rebalance, which is a
different data shape and far too slow to fetch per-name.

This module keeps a wide panel (dates x symbols) of SPLIT- AND DIVIDEND-
ADJUSTED closes plus raw volume, cached as Parquet. Adjustment is not optional:
an unadjusted return series produces a violent fake signal on every bonus issue
or split, and reversal/momentum factors are computed directly from returns.

Prices come from yfinance because it is already a proven dependency here. The
fetch is isolated in _download() so the source can be swapped (jugaad-data
bhavcopy is the natural upgrade) without touching the rest of the pipeline.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import yfinance as yf

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

PRICE_DIR = DATA_DIR / "prices"
CLOSE_FILE = PRICE_DIR / "close.parquet"
VOLUME_FILE = PRICE_DIR / "volume.parquet"

# yfinance handles multi-ticker requests in one HTTP round trip. ~25 symbols
# took 2.8s in testing; batching keeps memory flat and lets a single failed
# batch fail alone rather than taking the whole universe with it.
BATCH_SIZE = 60
BATCH_PAUSE_SEC = 0.4


class PriceStore:
    """
    Wide daily price panel for the factor universe.

        store = PriceStore()
        store.update(symbols, start="2019-01-01")
        px  = store.close()      # DataFrame: DatetimeIndex x symbol
        adv = store.adv_cr(63)   # average daily traded value, Rs. crore
    """

    def __init__(self, price_dir: Path = None):
        self.dir = price_dir or PRICE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────
    # Fetch
    # ──────────────────────────────────────────
    @staticmethod
    def _download(tickers: list[str], start: str, end: str) -> Optional[pd.DataFrame]:
        """One batched yfinance call. auto_adjust=True is required — see module docstring."""
        try:
            return yf.download(
                tickers,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="column",
            )
        except Exception as e:
            logger.warning(f"Batch download failed ({len(tickers)} tickers): {e}")
            return None

    @staticmethod
    def _field(raw: pd.DataFrame, field: str, tickers: list[str]) -> pd.DataFrame:
        """
        Pull one field out of a yfinance result.

        yfinance returns a flat frame for a single ticker and a MultiIndex for
        several, so both shapes have to be handled or single-name universes
        silently break.
        """
        if raw is None or raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            if field not in raw.columns.get_level_values(0):
                return pd.DataFrame()
            out = raw[field].copy()
        else:
            if field not in raw.columns:
                return pd.DataFrame()
            out = raw[[field]].copy()
            out.columns = tickers[:1]
        # Strip the ".NS" suffix so the panel is keyed by plain NSE symbol.
        out.columns = [str(c).replace(".NS", "") for c in out.columns]
        return out.dropna(axis=1, how="all")

    def update(self, symbols: Iterable[str], start: str = "2019-01-01",
               end: str = None, batch_size: int = BATCH_SIZE) -> dict:
        """
        Fetch and merge price history for `symbols` into the cached panel.

        Existing cached values are preserved and overwritten only where the new
        data is non-null, so a batch that comes back empty can never blank out
        history that was already good.
        """
        symbols = sorted({s.strip().upper() for s in symbols if s and str(s).strip()})
        end = end or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if not symbols:
            logger.warning("PriceStore.update called with no symbols")
            return {"requested": 0, "fetched": 0}

        logger.info(f"Updating price panel: {len(symbols)} symbols, {start} -> {end}")
        close_parts, vol_parts = [], []

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            tickers = [f"{s}.NS" for s in batch]
            raw = self._download(tickers, start, end)

            c = self._field(raw, "Close", tickers)
            v = self._field(raw, "Volume", tickers)
            if not c.empty:
                close_parts.append(c)
            if not v.empty:
                vol_parts.append(v)

            logger.info(
                f"  batch {i // batch_size + 1}/{(len(symbols) - 1) // batch_size + 1}: "
                f"{c.shape[1] if not c.empty else 0}/{len(batch)} symbols returned data"
            )
            time.sleep(BATCH_PAUSE_SEC)

        new_close = pd.concat(close_parts, axis=1) if close_parts else pd.DataFrame()
        new_vol = pd.concat(vol_parts, axis=1) if vol_parts else pd.DataFrame()

        merged_close = self._merge(self._read(CLOSE_FILE), new_close)
        merged_vol = self._merge(self._read(VOLUME_FILE), new_vol)

        self._write(CLOSE_FILE, merged_close)
        self._write(VOLUME_FILE, merged_vol)

        stats = {
            "requested": len(symbols),
            "fetched": int(new_close.shape[1]) if not new_close.empty else 0,
            "panel_symbols": int(merged_close.shape[1]) if not merged_close.empty else 0,
            "panel_days": int(merged_close.shape[0]) if not merged_close.empty else 0,
        }
        logger.info(
            f"Price panel now {stats['panel_days']} days x {stats['panel_symbols']} symbols"
        )
        return stats

    # ──────────────────────────────────────────
    # Storage
    # ──────────────────────────────────────────
    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(path)
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            logger.warning(f"Could not read {path.name}: {e}")
            return pd.DataFrame()

    @staticmethod
    def _write(path: Path, df: pd.DataFrame):
        if df.empty:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        df.sort_index().to_parquet(path)

    @staticmethod
    def _merge(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        """Union of rows and columns; new non-null values win."""
        if old.empty:
            return new
        if new.empty:
            return old
        for frame in (old, new):
            frame.index = pd.to_datetime(frame.index)
        combined = new.combine_first(old)
        return combined.sort_index()

    # ──────────────────────────────────────────
    # Access
    # ──────────────────────────────────────────
    def close(self) -> pd.DataFrame:
        """Adjusted closes: DatetimeIndex x symbol."""
        return self._read(CLOSE_FILE)

    def volume(self) -> pd.DataFrame:
        """Raw share volume: DatetimeIndex x symbol."""
        return self._read(VOLUME_FILE)

    def adv_cr(self, window: int = 63, as_of=None) -> pd.Series:
        """
        Average daily traded VALUE over the `window` sessions ending at `as_of`,
        in Rs. crore.

        Value, not share count: a liquidity floor has to be about rupees you can
        actually move. 1 crore = 1e7.

        `as_of` is NOT optional in spirit. Without it this returned the trailing
        window of the whole panel regardless of the date being scored, so a
        backtest asked to rank 2025-06-30 screened its universe using volume
        from 2026 — deciding what was tradeable in the past using the future.
        The factor engine's point-in-time gate caught exactly this.
        """
        px, vol = self.close(), self.volume()
        if px.empty or vol.empty:
            return pd.Series(dtype=float)

        if as_of is not None:
            ts = pd.Timestamp(as_of)
            px = px.loc[px.index <= ts]
            vol = vol.loc[vol.index <= ts]
            if px.empty or vol.empty:
                return pd.Series(dtype=float)

        common = px.columns.intersection(vol.columns)
        turnover = (px[common] * vol[common]).tail(window)
        return (turnover.mean() / 1e7).dropna().sort_values(ascending=False)

    def coverage(self) -> dict:
        px = self.close()
        if px.empty:
            return {"symbols": 0, "days": 0}
        return {
            "symbols": int(px.shape[1]),
            "days": int(px.shape[0]),
            "start": str(px.index.min().date()),
            "end": str(px.index.max().date()),
            "median_history_days": int(px.notna().sum().median()),
        }
