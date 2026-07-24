"""
Political Alpha Tracker — SQLite Cache Manager

Centralized caching layer. All modules read/write through this interface
instead of managing their own database connections.

Tables:
    companies       — BSE-listed companies with CIN, sector, market cap
    directors       — Company directors with DIN, resolved from MCA
    donors          — Electoral Trust / Bond donor records
    announcements   — BSE corporate announcements (cached for contract scoring)
    held_positions  — Companies with active alerts (auto-managed by notifier)
    system_log      — Pipeline health tracking (run counts, errors, node counts)
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any
from contextlib import contextmanager

from src.config import CACHE_DB, DATA_DIR

logger = logging.getLogger(__name__)


class CacheManager:
    """Thread-safe SQLite cache with auto-table-creation and TTL support."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or CACHE_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self):
        """Create all tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    scrip_code  TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    isin        TEXT,
                    cin         TEXT,
                    sector      TEXT,
                    industry    TEXT,
                    market_cap  REAL,
                    face_value  REAL,
                    in_watchlist INTEGER DEFAULT 0,
                    last_updated TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS directors (
                    din         TEXT NOT NULL,
                    cin         TEXT NOT NULL,
                    name        TEXT NOT NULL,
                    designation TEXT,
                    last_updated TEXT NOT NULL,
                    PRIMARY KEY (din, cin)
                );

                CREATE TABLE IF NOT EXISTS donors (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    donor_name      TEXT NOT NULL,
                    donor_cin       TEXT,
                    amount          REAL NOT NULL,
                    trust_name      TEXT,
                    recipient_party TEXT,
                    year            INTEGER NOT NULL,
                    source          TEXT NOT NULL,
                    last_updated    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS announcements (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    scrip_code  TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    category    TEXT,
                    is_contract INTEGER DEFAULT 0,
                    is_board_change INTEGER DEFAULT 0,
                    processed   INTEGER DEFAULT 0,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS held_positions (
                    scrip_code  TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    alert_date  TEXT NOT NULL,
                    alpha_score REAL,
                    expires_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    module      TEXT NOT NULL,
                    event       TEXT NOT NULL,
                    details     TEXT,
                    level       TEXT DEFAULT 'INFO'
                );

                CREATE INDEX IF NOT EXISTS idx_announcements_scrip
                    ON announcements(scrip_code, date);
                CREATE INDEX IF NOT EXISTS idx_directors_cin
                    ON directors(cin);
                CREATE INDEX IF NOT EXISTS idx_donors_cin
                    ON donors(donor_cin);
                CREATE INDEX IF NOT EXISTS idx_donors_year
                    ON donors(year);
            """)

    # ──────────────────────────────────────────
    # Company Operations
    # ──────────────────────────────────────────
    def upsert_company(self, scrip_code: str, name: str, isin: str = None,
                       cin: str = None, sector: str = None, industry: str = None,
                       market_cap: float = None, face_value: float = None,
                       in_watchlist: int = 0):
        """Insert or update a company record."""
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO companies
                    (scrip_code, name, isin, cin, sector, industry,
                     market_cap, face_value, in_watchlist, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scrip_code) DO UPDATE SET
                    name = excluded.name,
                    isin = COALESCE(excluded.isin, companies.isin),
                    cin = COALESCE(excluded.cin, companies.cin),
                    sector = COALESCE(excluded.sector, companies.sector),
                    industry = COALESCE(excluded.industry, companies.industry),
                    market_cap = COALESCE(excluded.market_cap, companies.market_cap),
                    face_value = COALESCE(excluded.face_value, companies.face_value),
                    in_watchlist = excluded.in_watchlist,
                    last_updated = excluded.last_updated
            """, (scrip_code, name, isin, cin, sector, industry,
                  market_cap, face_value, in_watchlist,
                  datetime.now().isoformat()))

    def get_company(self, scrip_code: str) -> Optional[dict]:
        """Get a company by scrip code."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM companies WHERE scrip_code = ?",
                (scrip_code,)
            ).fetchone()
            return dict(row) if row else None

    def get_company_by_cin(self, cin: str) -> Optional[dict]:
        """Get a company by CIN."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM companies WHERE cin = ?", (cin,)
            ).fetchone()
            return dict(row) if row else None

    def get_watchlist(self) -> list[dict]:
        """Get all companies currently in the watchlist."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM companies WHERE in_watchlist = 1"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_companies(self) -> list[dict]:
        """Get all companies in the database."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM companies").fetchall()
            return [dict(r) for r in rows]

    def clear_watchlist_flags(self):
        """Reset all watchlist flags (before regenerating)."""
        with self._connect() as conn:
            conn.execute("UPDATE companies SET in_watchlist = 0")

    # ──────────────────────────────────────────
    # Director Operations
    # ──────────────────────────────────────────
    def upsert_directors(self, cin: str, directors: list[dict]):
        """
        Bulk upsert directors for a company.
        Each dict should have keys: din, name, designation (optional).
        """
        now = datetime.now().isoformat()
        with self._connect() as conn:
            for d in directors:
                conn.execute("""
                    INSERT INTO directors (din, cin, name, designation, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(din, cin) DO UPDATE SET
                        name = excluded.name,
                        designation = COALESCE(excluded.designation, directors.designation),
                        last_updated = excluded.last_updated
                """, (d["din"], cin, d["name"], d.get("designation"), now))

    def get_directors_for_company(self, cin: str) -> list[dict]:
        """Get all directors for a company by CIN."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM directors WHERE cin = ?", (cin,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_companies_for_director(self, din: str) -> list[dict]:
        """Get all companies a director sits on (by DIN)."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT d.cin, c.name, c.scrip_code, c.sector
                FROM directors d
                LEFT JOIN companies c ON d.cin = c.cin
                WHERE d.din = ?
            """, (din,)).fetchall()
            return [dict(r) for r in rows]

    def is_director_cache_fresh(self, cin: str, ttl_days: int) -> bool:
        """Check if director data for a company is still fresh."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(last_updated) as latest FROM directors WHERE cin = ?",
                (cin,)
            ).fetchone()
            if not row or not row["latest"]:
                return False
            last_updated = datetime.fromisoformat(row["latest"])
            return (datetime.now() - last_updated).days < ttl_days

    # ──────────────────────────────────────────
    # Donor Operations
    # ──────────────────────────────────────────
    def upsert_donor(self, donor_name: str, amount: float, year: int,
                     trust_name: str = None, recipient_party: str = None,
                     donor_cin: str = None, source: str = "electoral_trust"):
        """Insert or update a donor record."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            # Check if this exact donor-trust-year combo exists
            existing = conn.execute("""
                SELECT id FROM donors
                WHERE donor_name = ? AND trust_name = ? AND year = ? AND source = ?
            """, (donor_name, trust_name, year, source)).fetchone()

            if existing:
                conn.execute("""
                    UPDATE donors SET
                        amount = ?, recipient_party = ?,
                        donor_cin = COALESCE(?, donor_cin),
                        last_updated = ?
                    WHERE id = ?
                """, (amount, recipient_party, donor_cin, now, existing["id"]))
            else:
                conn.execute("""
                    INSERT INTO donors
                        (donor_name, donor_cin, amount, trust_name,
                         recipient_party, year, source, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (donor_name, donor_cin, amount, trust_name,
                      recipient_party, year, source, now))

    def get_donors(self, min_year: int = None,
                   min_amount: float = None) -> list[dict]:
        """Get donor records with optional filters."""
        query = "SELECT * FROM donors WHERE 1=1"
        params = []
        if min_year:
            query += " AND year >= ?"
            params.append(min_year)
        if min_amount:
            query += " AND amount >= ?"
            params.append(min_amount)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_donors_by_cin(self, cin: str) -> list[dict]:
        """Get all donation records for a specific donor CIN."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM donors WHERE donor_cin = ?", (cin,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ──────────────────────────────────────────
    # Announcement Operations
    # ──────────────────────────────────────────
    def insert_announcement(self, scrip_code: str, title: str, date: str,
                            category: str = None, is_contract: bool = False,
                            is_board_change: bool = False):
        """Insert a new announcement (skip duplicates by title+date+scrip)."""
        with self._connect() as conn:
            existing = conn.execute("""
                SELECT id FROM announcements
                WHERE scrip_code = ? AND title = ? AND date = ?
            """, (scrip_code, title, date)).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO announcements
                        (scrip_code, title, date, category, is_contract,
                         is_board_change, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (scrip_code, title, date, category,
                      int(is_contract), int(is_board_change),
                      datetime.now().isoformat()))

    def get_contract_announcement_count(self, scrip_code: str,
                                         lookback_days: int = 365) -> int:
        """Count contract-related announcements in the lookback window."""
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM announcements
                WHERE scrip_code = ? AND is_contract = 1 AND date >= ?
            """, (scrip_code, cutoff)).fetchone()
            return row["cnt"] if row else 0

    def get_unprocessed_contracts(self) -> list[dict]:
        """Get contract announcements that haven't been processed yet."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT a.*, c.name as company_name, c.cin, c.sector
                FROM announcements a
                JOIN companies c ON a.scrip_code = c.scrip_code
                WHERE a.is_contract = 1 AND a.processed = 0
                ORDER BY a.date DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def mark_announcement_processed(self, announcement_id: int):
        """Mark an announcement as processed."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE announcements SET processed = 1 WHERE id = ?",
                (announcement_id,)
            )

    # ──────────────────────────────────────────
    # Held Positions Operations
    # ──────────────────────────────────────────
    def add_held_position(self, scrip_code: str, name: str,
                          alpha_score: float = None,
                          expiry_days: int = 180):
        """Add a company to held positions after an alert fires."""
        now = datetime.now()
        expires = (now + timedelta(days=expiry_days)).isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO held_positions
                    (scrip_code, name, alert_date, alpha_score, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scrip_code) DO UPDATE SET
                    alert_date = excluded.alert_date,
                    alpha_score = excluded.alpha_score,
                    expires_at = excluded.expires_at
            """, (scrip_code, name, now.isoformat(), alpha_score, expires))

    def remove_held_position(self, scrip_code: str):
        """Remove a company from held positions (trade exited)."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM held_positions WHERE scrip_code = ?",
                (scrip_code,)
            )

    def get_held_positions(self) -> list[dict]:
        """Get all current (non-expired) held positions."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM held_positions WHERE expires_at > ?",
                (now,)
            ).fetchall()
            return [dict(r) for r in rows]

    def cleanup_expired_positions(self) -> int:
        """Remove expired held positions. Returns count removed."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM held_positions WHERE expires_at <= ?", (now,)
            )
            return cursor.rowcount

    # ──────────────────────────────────────────
    # System Logging
    # ──────────────────────────────────────────
    def log_event(self, module: str, event: str,
                  details: str = None, level: str = "INFO"):
        """Log a pipeline event for monitoring."""
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO system_log (timestamp, module, event, details, level)
                VALUES (?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), module, event, details, level))

    # ──────────────────────────────────────────
    # Monitoring Helpers
    # ──────────────────────────────────────────
    def get_table_counts(self) -> dict:
        """Get row counts for all tables (for health monitoring)."""
        tables = ["companies", "directors", "donors",
                  "announcements", "held_positions"]
        counts = {}
        with self._connect() as conn:
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                counts[table] = row["cnt"]
            # Also get watchlist count
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM companies WHERE in_watchlist = 1"
            ).fetchone()
            counts["watchlist"] = row["cnt"]
        return counts
