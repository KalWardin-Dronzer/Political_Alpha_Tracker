"""
Purge fabricated demo rows from the paper-trading tables.

WHY THIS EXISTS
---------------
A since-deleted helper, `populate_demo_db.py`, seeded `virtual_portfolio` with
five fake positions so the Streamlit dashboard would not look empty:

    buy_price       = 100.0 + (i * 15)      -> 100, 115, 130, 145, 160
    conviction_score = alpha_graph.score + 4.0  -> 4.51
    buy_date        = "2026-07-03"           (hardcoded)

Those prices are fiction. The real quotes for the seeded scrips are roughly
Torrent Pharma ~Rs.3,000, Alkem ~Rs.5,000, Divi's ~Rs.6,000. When
PaperTrader.execute_sells() closes such a position it books

    net_pnl = (REAL sale price x qty) - (FAKE invested amount)

into `trade_history`, i.e. a fabricated ~2,500% winner. WeeklyTearsheet reports
SUM(net_pnl) straight from that table, so the fake gains would surface as a
headline performance number.

USAGE
-----
    python purge_demo_data.py            # dry run: report only, changes nothing
    python purge_demo_data.py --apply    # delete the identified rows

Run it wherever the live DB lives (on EC2: inside ~/Insider-trading).
"""

import argparse
import sys

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
from src.config import CACHE_DB

# Signature of the seeded rows. Deliberately narrow: buy_date is the hardcoded
# literal from the demo script AND the price must sit on the exact 100+15i
# sequence. A real trade matching both is implausible.
DEMO_BUY_DATE = "2026-07-03"
DEMO_PRICES = [100.0 + (i * 15) for i in range(5)]  # 100, 115, 130, 145, 160


def _fmt(rows, headers):
    if not rows:
        return "    (none)"
    widths = [max(len(str(h)), max(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    out = ["    " + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("    " + "  ".join("-" * w for w in widths))
    for r in rows:
        out.append("    " + "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Purge fabricated demo paper-trading rows.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete. Without this the script only reports.")
    args = ap.parse_args()

    cache = CacheManager()
    print(f"Database: {CACHE_DB}\n")

    price_ph = ",".join("?" * len(DEMO_PRICES))
    where = f"buy_date = ? AND buy_price IN ({price_ph})"
    params = [DEMO_BUY_DATE, *DEMO_PRICES]

    with cache._connect() as conn:
        open_rows = conn.execute(
            f"SELECT scrip_code, buy_date, buy_price, quantity, invested_amount, "
            f"conviction_score FROM virtual_portfolio WHERE {where}", params
        ).fetchall()

        closed_rows = conn.execute(
            f"SELECT scrip_code, buy_date, sell_date, buy_price, sell_price, quantity, "
            f"net_pnl FROM trade_history WHERE {where}", params
        ).fetchall()

        total_open = conn.execute("SELECT COUNT(*) FROM virtual_portfolio").fetchone()[0]
        total_closed = conn.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0]

    print(f"OPEN demo positions in virtual_portfolio ({len(open_rows)} of {total_open} total):")
    print(_fmt(open_rows, ["scrip", "buy_date", "buy_px", "qty", "invested", "conviction"]))

    print(f"\nCLOSED demo trades in trade_history ({len(closed_rows)} of {total_closed} total):")
    print(_fmt(closed_rows, ["scrip", "buy_date", "sell_date", "buy_px", "sell_px", "qty", "net_pnl"]))

    if closed_rows:
        fake_pnl = sum(r[6] or 0 for r in closed_rows)
        print(f"\n  >> These contribute Rs.{fake_pnl:,.2f} of FABRICATED realised P&L")
        print( "     to the weekly tearsheet. This is not a real result.")

    if not open_rows and not closed_rows:
        print("\nNothing to purge — this database is clean.")
        return 0

    if not args.apply:
        print("\nDRY RUN — nothing deleted. Re-run with --apply to remove these rows.")
        return 0

    with cache._connect() as conn:
        d1 = conn.execute(f"DELETE FROM virtual_portfolio WHERE {where}", params).rowcount
        d2 = conn.execute(f"DELETE FROM trade_history WHERE {where}", params).rowcount
        conn.commit()

    print(f"\nDeleted {d1} open position(s) and {d2} closed trade(s).")
    cache.log_event("purge_demo_data", "demo_rows_purged",
                    f"virtual_portfolio: {d1}, trade_history: {d2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
