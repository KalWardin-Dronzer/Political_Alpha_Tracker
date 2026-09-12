"""
Political Alpha Tracker — single entry point.

    python cli.py --help

WHY THIS FILE EXISTS
--------------------
The repo root had accumulated fourteen top-level scripts, five of them named
`test_*.py` (which pytest tried to collect as tests). Working out which one to
run, and in what order, had become its own problem. Everything is reachable
from here now, with the operational jobs listed first.

TWO ENTRY POINTS ARE DELIBERATELY LEFT AT THE ROOT AND UNCHANGED:

    main.py      the daily pipeline. The EC2 cron runs `python main.py`
                 directly; changing that path would silently break production.
    refresh.py   reference-data refresh, invoked by hand and by three GitHub
                 workflows as `python refresh.py --mode ...`.

`cli.py daily` and `cli.py refresh` delegate to those same modules, so either
form works and neither can drift from the other.
"""

import argparse
import sys


# ── operational ──────────────────────────────────────────────────
def cmd_daily(args):
    """Run the daily pipeline (same as `python main.py`)."""
    import main
    return main.main() or 0


def cmd_refresh(args):
    """Refresh reference data: donors, directors, watchlist, graph."""
    sys.argv = ["refresh.py", "--mode", args.mode]
    import refresh
    return refresh.main() or 0


def cmd_prices(args):
    """Build or update the adjusted daily price panel."""
    sys.argv = ["build_price_panel.py", "--start", args.start]
    if args.limit:
        sys.argv += ["--limit", str(args.limit)]
    from scripts.research import build_price_panel
    return build_price_panel.main() or 0


def cmd_dashboard(args):
    """Print how to launch the Streamlit dashboard."""
    print("Streamlit has to own the process, so run it directly:\n")
    print("    streamlit run app.py\n")
    return 0


# ── research ─────────────────────────────────────────────────────
def cmd_research(args):
    """Run a backtest or validation study."""
    if args.study == "event":
        from scripts.research import run_backtest
        return run_backtest.main() if hasattr(run_backtest, "main") else 0
    if args.study == "factor":
        from scripts.research import run_factor_validation
        return run_factor_validation.main() or 0
    if args.study == "controls":
        from scripts.research import run_factor_diagnostics
        return run_factor_diagnostics.main() or 0
    if args.study == "universe":
        from scripts.research import run_universe_test
        return run_universe_test.main() or 0
    if args.study == "lead-lag":
        from scripts.research import run_lead_lag
        return run_lead_lag.main() or 0
    print(f"unknown study: {args.study}")
    return 1


def cmd_trials(args):
    """Show the backtest trial log — the count deflated Sharpe is computed against."""
    from src.research.factor_backtest import TrialLog
    log = TrialLog()
    n = log.count()
    print(f"trials logged: {n}")
    if n:
        srs = log.all_sharpes()
        if srs:
            print(f"net Sharpe across trials: min {min(srs):.3f}  "
                  f"median {sorted(srs)[len(srs)//2]:.3f}  max {max(srs):.3f}")
        print(f"\nEvery configuration ever tested is in {log.path}.")
        print("Deflating against a count that omits trials understates overfitting,")
        print("so do not prune this file.")
    return 0


# ── maintenance ──────────────────────────────────────────────────
def cmd_purge_demo(args):
    """Find and optionally delete seeded demo positions and fabricated trades."""
    sys.argv = ["purge_demo_data.py"] + (["--apply"] if args.apply else [])
    from scripts.research import purge_demo_data
    return purge_demo_data.main() or 0


def cmd_health(args):
    """Report whether reference data can support a political-connection alert."""
    import logging
    logging.basicConfig(level=logging.WARNING)
    from src.data.cache_manager import CacheManager
    from src.signals.graph_manager import GraphManager
    from src.data.delisting_registry import DelistingRegistry
    from src.data.price_store import PriceStore

    cache = CacheManager()
    with cache._connect() as conn:
        def one(q):
            try:
                return conn.execute(q).fetchone()[0]
            except Exception:
                return "n/a"
        companies = one("SELECT COUNT(*) FROM companies")
        with_cin = one("SELECT COUNT(*) FROM companies WHERE cin IS NOT NULL AND cin != ''")
        donors = one("SELECT COUNT(DISTINCT donor_name) FROM donors")
        directors = one("SELECT COUNT(*) FROM directors")

    graph = GraphManager(cache)
    graph.build_from_cache()
    panel = PriceStore().coverage()

    print("REFERENCE DATA")
    print(f"  companies ................ {companies}")
    print(f"  with a CIN ............... {with_cin}"
          f"  ({with_cin/companies*100:.1f}% — the binding constraint)"
          if isinstance(with_cin, int) and isinstance(companies, int) and companies
          else f"  with a CIN ............... {with_cin}")
    print(f"  distinct donors .......... {donors}")
    print(f"  directors ................ {directors}")
    print(f"  graph .................... {graph.G.number_of_nodes()} nodes, "
          f"{graph.G.number_of_edges()} edges")
    print(f"  price panel .............. {panel}")

    reg = DelistingRegistry()
    df = reg.load()
    if df.empty:
        print("  delisting registry ....... MISSING — backtests are uncorrected "
              "for survivorship (run `cli.py refresh --mode annual`)")
    else:
        est = reg.bias_estimate(companies if isinstance(companies, int) else 1588,
                                "2019-01-01", "2026-09-10")
        print(f"  delisting registry ....... {len(df)} records, "
              f"survivorship drag ~{est.annual_drag_pct*100:.3f}%/yr")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="Political Alpha Tracker — operations and research.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python cli.py daily                     run the daily pipeline\n"
            "  python cli.py health                    can an alert even fire today?\n"
            "  python cli.py prices --start 2019-01-01 build the price panel\n"
            "  python cli.py research universe         is the universe premium real?\n"
            "  python cli.py trials                    what has already been tested\n"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("daily", help="run the daily pipeline").set_defaults(fn=cmd_daily)
    sub.add_parser("health", help="reference-data health check").set_defaults(fn=cmd_health)
    sub.add_parser("dashboard", help="how to launch the dashboard").set_defaults(fn=cmd_dashboard)

    r = sub.add_parser("refresh", help="refresh reference data")
    # Mirrors refresh.py exactly. weekly_prune.yml calls `--mode prune`, so
    # inventing a different vocabulary here would make the CLI and the workflow
    # disagree about what the same job is called.
    r.add_argument("--mode", required=True,
                   choices=["quarterly", "annual", "prune"],
                   help="annual=donors, quarterly=watchlist+directors, prune=graph")
    r.set_defaults(fn=cmd_refresh)

    pr = sub.add_parser("prices", help="build/update the price panel")
    pr.add_argument("--start", default="2019-01-01")
    pr.add_argument("--limit", type=int, default=None)
    pr.set_defaults(fn=cmd_prices)

    rs = sub.add_parser("research", help="run a backtest or validation study")
    rs.add_argument("study",
                    choices=["event", "factor", "controls", "universe", "lead-lag"],
                    help="event=announcement study, factor=pre-declared grid, "
                         "controls=random/placebo controls, universe=premium test, "
                         "lead-lag=political peer lead-lag with placebo control")
    rs.set_defaults(fn=cmd_research)

    sub.add_parser("trials", help="show the backtest trial log").set_defaults(fn=cmd_trials)

    pg = sub.add_parser("purge-demo", help="remove seeded demo portfolio rows")
    pg.add_argument("--apply", action="store_true",
                    help="actually delete (default is a dry run)")
    pg.set_defaults(fn=cmd_purge_demo)

    return p


def main():
    args = build_parser().parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
