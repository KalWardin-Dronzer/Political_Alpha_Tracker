"""
Resolve directors for every company CIN, so the political graph has the bridge
it needs.

    python scripts/research/backfill_directors.py --limit 5   # smoke test
    python scripts/research/backfill_directors.py             # full run
    python scripts/research/backfill_directors.py --status
    python scripts/research/backfill_directors.py --rebuild-graph

WHY THIS IS THE STEP THAT MATTERS
---------------------------------
A political connection is a PATH: company -> director -> donor company -> trust.
The CIN backfill lifted coverage from 3% to 92.6%, but CINs alone create no
edges. Without directors there is no bridge from a company to a donor, so the
graph stayed at 214 nodes and every test of the political hypothesis stayed
underpowered — 20 connected companies out of 1,589.

This run is therefore the actual test of whether that hypothesis was
underpowered or simply wrong.

MCAResolver already does the work per CIN and writes directors straight to the
database, checking the cache first. What it lacks for a 1,463-CIN run is
resumability and progress, which is all this script adds: it selects only CINs
with no directors on file, so an interrupted run resumes exactly where it
stopped, and it never re-scrapes a company that already resolved.
"""

import argparse
import logging
import sys
import time

# Allow running this file directly (python scripts/research/<name>.py) as well
# as through cli.py. Without this the repo root is not on sys.path and the
# `src` package cannot be imported.
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from src.data.cache_manager import CacheManager
from src.data.mca_resolver import MCAResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
for noisy in ("urllib3", "src.data.mca_resolver"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("backfill_directors")


def pending(cache, limit=None):
    """CINs with no directors on file — this is what makes the run resumable."""
    sql = """
        SELECT c.cin, c.name, c.nse_symbol
        FROM companies c
        WHERE c.cin IS NOT NULL AND c.cin != ''
          AND NOT EXISTS (SELECT 1 FROM directors d WHERE d.cin = c.cin)
        ORDER BY c.name
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with cache._connect() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def cmd_status(cache):
    with cache._connect() as conn:
        def one(q):
            return conn.execute(q).fetchone()[0]
        cins = one("SELECT COUNT(*) FROM companies WHERE cin IS NOT NULL AND cin != ''")
        with_dir = one("SELECT COUNT(DISTINCT cin) FROM directors")
        directors = one("SELECT COUNT(*) FROM directors")
        bureaucrats = one("SELECT COUNT(*) FROM directors WHERE is_bureaucrat = 1")
        donors = one("SELECT COUNT(DISTINCT donor_name) FROM donors")
        # The donors table names this column donor_cin, not cin.
        donor_cins = one(
            "SELECT COUNT(DISTINCT donor_cin) FROM donors "
            "WHERE donor_cin IS NOT NULL AND donor_cin != ''")
    print(f"companies with a CIN ......... {cins}")
    print(f"  CINs with directors ........ {with_dir}"
          + (f"  ({with_dir/cins*100:.1f}%)" if cins else ""))
    print(f"  director rows .............. {directors}")
    print(f"  flagged as bureaucrat ...... {bureaucrats}")
    print(f"  distinct donors ............ {donors}")
    print(f"  donors resolved to a CIN ... {donor_cins}")
    print(f"  still to resolve ........... {cins - with_dir}")
    return 0


def cmd_rebuild_graph(cache):
    """Rebuild the graph from the database and report the connected universe."""
    from src.signals.graph_manager import GraphManager
    g = GraphManager(cache)
    g.build_from_cache()
    g.save()
    print(f"graph: {g.G.number_of_nodes()} nodes, {g.G.number_of_edges()} edges")

    with cache._connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT cin, name, nse_symbol FROM companies "
            "WHERE cin IS NOT NULL AND cin != ''").fetchall()]
    connected = [r for r in rows if g.alpha_query(r["cin"])]
    print(f"companies with a political connection: {len(connected)} of {len(rows)}"
          f"  ({len(connected)/len(rows)*100:.1f}%)" if rows else "")
    for r in connected[:25]:
        print(f"    {str(r['nse_symbol'])[:12]:12} {str(r['name'])[:44]}")
    if len(connected) > 25:
        print(f"    ... and {len(connected) - 25} more")
    cache.log_event("graph", "rebuilt",
                    f"{g.G.number_of_nodes()} nodes, {len(connected)} connected")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Resolve directors for company CINs.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rebuild-graph", action="store_true",
                    help="rebuild the graph from cached data and report connections")
    args = ap.parse_args()

    cache = CacheManager()
    if args.status:
        return cmd_status(cache)
    if args.rebuild_graph:
        return cmd_rebuild_graph(cache)

    todo = pending(cache, args.limit)
    if not todo:
        logger.info("Every CIN already has directors on file.")
        return cmd_status(cache)

    logger.info(f"resolving directors for {len(todo)} CINs "
                f"(MCA portal -> Zaubacorp -> data.gov.in per company)")
    mca = MCAResolver(cache)

    got = 0
    t0 = time.time()
    for i, row in enumerate(todo, 1):
        try:
            directors = mca.resolve_directors(row["cin"])
        except KeyboardInterrupt:
            logger.warning("interrupted — directors resolved so far are already saved")
            break
        except Exception as e:
            logger.warning(f"  {str(row['name'])[:36]}: {type(e).__name__}: {e}")
            continue
        if directors:
            got += 1
        if i % 20 == 0 or i == len(todo):
            elapsed = time.time() - t0
            eta = (elapsed / i) * (len(todo) - i) / 60
            logger.info(f"  {i}/{len(todo)}  with directors {got} "
                        f"({got/i*100:.0f}%)  ETA {eta:.0f} min")

    logger.info(f"done: {got} of {len(todo)} companies got directors")
    print()
    cmd_status(cache)
    print()
    return cmd_rebuild_graph(cache)


if __name__ == "__main__":
    sys.exit(main())
