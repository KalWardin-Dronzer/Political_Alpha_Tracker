"""
Backfill CINs for the company universe.

    python scripts/research/backfill_cins.py --limit 10     # smoke test
    python scripts/research/backfill_cins.py                # full run
    python scripts/research/backfill_cins.py --status        # progress
    python scripts/research/backfill_cins.py --promote       # stage -> companies.cin

SAFETY DESIGN
-------------
Results land in a STAGING table (cin_resolution), never straight into
companies.cin. Promotion is a separate, explicit step so the whole batch can be
inspected first. This matters more than usual here: a wrong CIN attaches
another company's directors to the political graph and manufactures a
connection that does not exist, which is invisible once it is in place.

Every row is committed as it is resolved, so an interrupted run loses nothing
and re-running skips what is already attempted. Refusals are recorded too —
with the reason — so a later run can retry just those without redoing the
successes, and so the refusal rate stays auditable.

Promotion NEVER overwrites an existing CIN. The 48 already on file were
verified against this resolver at 100% precision; they are not up for revision
by a scraper.
"""

import argparse
import logging
import sys
import time

# Allow running this file directly (python scripts/research/<name>.py) as well
# as through cli.py. Without this the repo root is not on sys.path and the
# `src` package cannot be imported — a regression introduced when these scripts
# moved out of the repo root.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from src.data.cache_manager import CacheManager
from src.data.cin_resolver import CinResolver, CIN_RE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger("backfill_cins")

DDL = """
CREATE TABLE IF NOT EXISTS cin_resolution (
    scrip_code    TEXT PRIMARY KEY,
    name          TEXT,
    nse_symbol    TEXT,
    resolved_cin  TEXT,
    matched_name  TEXT,
    score         REAL,
    n_candidates  INTEGER,
    reason        TEXT,
    resolved_at   TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def ensure_table(cache):
    with cache._connect() as conn:
        conn.execute(DDL)
        conn.commit()


def pending(cache, retry_failed: bool, limit: int = None):
    """Companies with no CIN that have not been attempted yet."""
    sql = """
        SELECT c.scrip_code, c.name, c.nse_symbol
        FROM companies c
        LEFT JOIN cin_resolution r ON r.scrip_code = c.scrip_code
        WHERE (c.cin IS NULL OR c.cin = '')
          AND c.name IS NOT NULL AND c.name != ''
          AND (r.scrip_code IS NULL {retry})
        ORDER BY c.name
    """.format(retry="OR r.resolved_cin IS NULL" if retry_failed else "")
    if limit:
        sql += f" LIMIT {int(limit)}"
    with cache._connect() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def record(cache, row, match):
    """Commit one result immediately — this is the checkpoint."""
    with cache._connect() as conn:
        conn.execute(
            """INSERT INTO cin_resolution
               (scrip_code, name, nse_symbol, resolved_cin, matched_name,
                score, n_candidates, reason, resolved_at)
               VALUES (?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
               ON CONFLICT(scrip_code) DO UPDATE SET
                 resolved_cin=excluded.resolved_cin,
                 matched_name=excluded.matched_name,
                 score=excluded.score,
                 n_candidates=excluded.n_candidates,
                 reason=excluded.reason,
                 resolved_at=CURRENT_TIMESTAMP""",
            (row["scrip_code"], row["name"], row.get("nse_symbol"),
             match.cin, match.matched_name, float(match.score),
             int(match.n_candidates), match.reason),
        )
        conn.commit()


def cmd_status(cache):
    with cache._connect() as conn:
        tot = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        have = conn.execute(
            "SELECT COUNT(*) FROM companies WHERE cin IS NOT NULL AND cin != ''"
        ).fetchone()[0]
        try:
            att = conn.execute("SELECT COUNT(*) FROM cin_resolution").fetchone()[0]
            ok = conn.execute(
                "SELECT COUNT(*) FROM cin_resolution WHERE resolved_cin IS NOT NULL"
            ).fetchone()[0]
            dupes = conn.execute(
                """SELECT COUNT(*) FROM (
                     SELECT resolved_cin FROM cin_resolution
                     WHERE resolved_cin IS NOT NULL
                     GROUP BY resolved_cin HAVING COUNT(*) > 1)"""
            ).fetchone()[0]
            reasons = conn.execute(
                """SELECT reason, COUNT(*) c FROM cin_resolution
                   WHERE resolved_cin IS NULL
                   GROUP BY reason ORDER BY c DESC LIMIT 6"""
            ).fetchall()
        except Exception:
            att = ok = dupes = 0
            reasons = []

    print(f"companies ................ {tot}")
    print(f"  already have a CIN ..... {have}  ({have/tot*100:.1f}%)")
    print(f"  staged attempts ........ {att}")
    print(f"  staged resolutions ..... {ok}"
          + (f"  ({ok/att*100:.0f}% hit rate)" if att else ""))
    print(f"  CINs staged more than once: {dupes}"
          + ("   <- inspect before promoting" if dupes else ""))
    if have + ok:
        print(f"  coverage after promotion: {have + ok}/{tot} "
              f"({(have + ok)/tot*100:.1f}%)")
    if reasons:
        print("\n  refusal reasons:")
        for r in reasons:
            print(f"    {r[1]:>5}  {str(r[0])[:66]}")
    return 0


def cmd_promote(cache, apply: bool):
    """Copy staged CINs into companies.cin. Never overwrites an existing value."""
    with cache._connect() as conn:
        rows = conn.execute(
            """SELECT r.scrip_code, r.name, r.resolved_cin, r.score
               FROM cin_resolution r
               JOIN companies c ON c.scrip_code = r.scrip_code
               WHERE r.resolved_cin IS NOT NULL
                 AND (c.cin IS NULL OR c.cin = '')"""
        ).fetchall()
        rows = [dict(r) for r in rows]

        # A CIN staged against two DIFFERENT companies means at least one is
        # wrong, so refuse both rather than promote a known-bad mapping.
        #
        # But one CIN legitimately covering two scrip codes is normal: a company
        # with two listed share classes shares a single CIN. JISLDVREQS and
        # JISLJALEQS are both Jain Irrigation Systems Limited (DVR and ordinary
        # equity). Blocking those would discard a correct mapping, so the test is
        # whether the COMPANY NAMES differ, not whether the CIN repeats.
        from src.data.cin_resolver import normalize
        seen, conflicts = {}, []
        for r in rows:
            key = r["resolved_cin"]
            prev = seen.get(key)
            if prev is None:
                seen[key] = r
            elif normalize(prev["name"]) != normalize(r["name"]):
                conflicts.append((prev, r))

        malformed = [r for r in rows if not CIN_RE.match(str(r["resolved_cin"]))]

    print(f"staged rows eligible for promotion: {len(rows)}")
    print(f"  malformed CINs ......... {len(malformed)}")
    print(f"  duplicate CINs ......... {len(conflicts)}")
    for a, b in conflicts[:10]:
        print(f"    {a['resolved_cin']}  <- {str(a['name'])[:34]}  AND  {str(b['name'])[:34]}")

    blocked = {r["scrip_code"] for r in malformed}
    for a, b in conflicts:
        blocked.add(a["scrip_code"])
        blocked.add(b["scrip_code"])
    good = [r for r in rows if r["scrip_code"] not in blocked]
    print(f"  will promote ........... {len(good)}  (skipping {len(blocked)} blocked)")

    if not apply:
        print("\nDRY RUN — re-run with --apply to write these to companies.cin")
        return 0

    with cache._connect() as conn:
        for r in good:
            conn.execute("UPDATE companies SET cin = ? WHERE scrip_code = ?",
                         (r["resolved_cin"], r["scrip_code"]))
        conn.commit()
    print(f"\npromoted {len(good)} CINs into companies.cin")
    cache.log_event("cin_backfill", "promoted", f"{len(good)} CINs")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Backfill company CINs via Zaubacorp.")
    ap.add_argument("--limit", type=int, default=None, help="only attempt N companies")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-attempt companies that previously refused")
    ap.add_argument("--delay", type=float, default=1.2, help="seconds between requests")
    ap.add_argument("--status", action="store_true", help="show progress and exit")
    ap.add_argument("--promote", action="store_true",
                    help="copy staged CINs into companies.cin (dry run unless --apply)")
    ap.add_argument("--apply", action="store_true", help="with --promote, actually write")
    args = ap.parse_args()

    cache = CacheManager()
    ensure_table(cache)

    if args.status:
        return cmd_status(cache)
    if args.promote:
        return cmd_promote(cache, args.apply)

    todo = pending(cache, args.retry_failed, args.limit)
    if not todo:
        logger.info("Nothing pending. Use --retry-failed to re-attempt refusals.")
        return cmd_status(cache)

    logger.info(f"resolving {len(todo)} companies at {args.delay}s/request "
                f"(~{len(todo)*args.delay*1.6/60:.0f} min estimated)")
    resolver = CinResolver(delay=args.delay)

    got = 0
    t0 = time.time()
    for i, row in enumerate(todo, 1):
        try:
            m = resolver.resolve(row["name"])
        except KeyboardInterrupt:
            logger.warning("interrupted — staged results are already committed")
            break
        except Exception as e:
            logger.warning(f"  {row['name'][:40]}: {type(e).__name__}: {e}")
            continue
        record(cache, row, m)
        if m.resolved:
            got += 1
        if i % 25 == 0 or i == len(todo):
            rate = got / i * 100
            elapsed = time.time() - t0
            eta = (elapsed / i) * (len(todo) - i) / 60
            logger.info(f"  {i}/{len(todo)}  resolved {got} ({rate:.0f}%)  "
                        f"ETA {eta:.0f} min")

    logger.info(f"done: {got} resolved of {len(todo)} attempted")
    print()
    return cmd_status(cache)


if __name__ == "__main__":
    sys.exit(main())
