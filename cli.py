"""
Political Alpha Tracker: do Indian listed companies that bought electoral
bonds behave differently in the stock market?

    python cli.py companies          rebuild the listed-company universe from NSE's lists
    python cli.py connections        which listed companies bought bonds
    python cli.py prices             download the daily price panel (Yahoo Finance)
    python cli.py study lead-lag     run one study (see `study --help`)
    python cli.py results            regenerate everything in results/
    python cli.py visualize --open   interactive graph of the connections
"""

import argparse
import contextlib
import logging
import sys

STUDIES = {
    "lead-lag": "lead_lag",          # political peer lead-lag, with a placebo arm
    "event-study": "event_study",    # did prices move when the buyers were revealed?
    "leadlag-rule": "leadlag_rule",  # can the size lead-lag be traded after costs?
    "factor": "factor",              # pre-declared factor grid with deflated Sharpe
    "controls": "controls",          # factor selection against random selection
    "universe": "universe",          # is the small/mid-cap premium real?
}


def cmd_connections(args):
    from src.config import RESULTS_DIR
    from src.connections import connections
    from src.data.bonds import load_bond_purchases
    from src.data.companies import load_companies

    bonds, companies = load_bond_purchases(), load_companies()
    table = connections(bonds, companies)
    print(f"bonds in the SBI disclosure ...... {len(bonds):,} "
          f"(Rs {bonds['amount'].sum() / 1e7:,.0f} crore, {bonds['purchaser'].nunique():,} purchasers)")
    print(f"listed companies in the universe .. {len(companies):,}")
    print(f"companies matched to bonds ........ {len(table)}")
    print(f"connected (a bond >= Rs 10 lakh) .. {int(table['connected'].sum())}")
    print()
    print("largest buyers (Rs crore):")
    for _, row in table.head(args.top).iterrows():
        print(f"  {row['name'][:42]:42} {row['total'] / 1e7:>8.1f}  {row['sector'] or '-'}")
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / "connections.csv"
    export = table.assign(total_crore=(table["total"] / 1e7).round(2),
                          first=table["first"].dt.date, last=table["last"].dt.date)
    export[["name", "nse_symbol", "sector", "bonds", "total_crore", "largest", "first",
            "last", "connected", "purchasers"]].to_csv(out, index_label="company")
    print(f"\nwrote {out.relative_to(RESULTS_DIR.parent)}")
    return 0


def cmd_companies(args):
    from src.data.build_companies import main
    return main()


def cmd_prices(args):
    from src.config import PRICE_END
    from src.data.companies import load_companies
    from src.data.price_store import PriceStore

    store = PriceStore()
    symbols = sorted({s for s in load_companies()["nse_symbol"] if s})
    if not args.all:
        have = set(store.close().columns)
        symbols = [s for s in symbols if s not in have]
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"downloading {len(symbols)} NSE symbols, {args.start} to {PRICE_END} (exclusive) ...")
    if symbols:
        store.update(symbols, start=args.start, end=PRICE_END)
    print(f"panel: {store.coverage()}")
    return 0


def cmd_study(args):
    import importlib
    module = importlib.import_module(f"studies.{STUDIES[args.name]}")
    return module.main() or 0


def cmd_results(args):
    """Regenerate results/: the connections table, every study's output and the figures."""
    from src.config import RESULTS_DIR
    from studies.figures import save_all

    RESULTS_DIR.mkdir(exist_ok=True)
    cmd_connections(argparse.Namespace(top=10))
    for name in STUDIES:
        path = RESULTS_DIR / f"{STUDIES[name]}.txt"
        print(f"\nrunning {name} -> {path.name}")
        with open(path, "w", encoding="utf-8") as out, contextlib.redirect_stdout(out):
            code = cmd_study(argparse.Namespace(name=name))
        if code:
            print(f"{name} failed with exit code {code}")
            return code
    for path in save_all(RESULTS_DIR / "figures"):
        print(f"wrote {path.relative_to(RESULTS_DIR.parent)}")
    return 0


def cmd_visualize(args):
    """Generate the interactive connection graph."""
    import webbrowser
    from src.graph import build_graph, save_html

    path = save_html(build_graph(), args.output)
    print(f"wrote {path}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_trials(args):
    """Show the backtest trial log, the count the deflated Sharpe ratio is computed against."""
    from src.research.factor_backtest import TrialLog

    log = TrialLog()
    n = log.count()
    print(f"trials logged: {n}")
    if n:
        sharpes = sorted(log.all_sharpes())
        if sharpes:
            print(f"net Sharpe across trials: min {sharpes[0]:.3f}  "
                  f"median {sharpes[len(sharpes) // 2]:.3f}  max {sharpes[-1]:.3f}")
        print(f"\nEvery configuration ever tested is in {log.path}. Deflating against a")
        print("count that omits trials understates overfitting, so do not prune it.")
    return 0


def cmd_cins(args):
    """Look up missing CINs and write candidates for review; never edits companies.csv."""
    import pandas as pd
    from src.config import RESULTS_DIR
    from src.data.cin_resolver import CinResolver
    from src.data.companies import load_companies

    companies = load_companies()
    missing = companies[companies["cin"] == ""]
    if args.limit:
        missing = missing.head(args.limit)
    print(f"resolving {len(missing)} companies without a CIN (about 1.2 s each) ...")
    resolver = CinResolver()
    rows = []
    for _, company in missing.iterrows():
        match = resolver.resolve(company["name"])
        rows.append({"scrip_code": company["scrip_code"], "name": company["name"],
                     "cin": match.cin or "", "matched_name": match.matched_name or "",
                     "score": match.score, "reason": match.reason or ""})
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / "cin_candidates.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    found = sum(1 for r in rows if r["cin"])
    print(f"found {found}, refused {len(rows) - found}; review {out} before copying any into data/companies.csv")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="cli.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("connections", help="match bond purchasers to listed companies")
    c.add_argument("--top", type=int, default=15, help="largest buyers to list")
    c.set_defaults(fn=cmd_connections)

    co = sub.add_parser("companies", help="rebuild data/companies.csv from the committed NSE lists")
    co.set_defaults(fn=cmd_companies)

    pr = sub.add_parser("prices", help="download the daily price panel, to the pinned end date")
    pr.add_argument("--start", default="2019-01-01")
    pr.add_argument("--all", action="store_true",
                    help="re-download every symbol, not only those missing from the panel")
    pr.add_argument("--limit", type=int, help="only the first N symbols (smoke test)")
    pr.set_defaults(fn=cmd_prices)

    s = sub.add_parser("study", help="run one study")
    s.add_argument("name", choices=list(STUDIES))
    s.set_defaults(fn=cmd_study)

    sub.add_parser("results", help="regenerate everything in results/").set_defaults(fn=cmd_results)

    v = sub.add_parser("visualize", help="interactive HTML graph of the connections")
    v.add_argument("--output", default="results/connections.html")
    v.add_argument("--open", action="store_true", help="open it in the browser")
    v.set_defaults(fn=cmd_visualize)

    sub.add_parser("trials", help="show the backtest trial log").set_defaults(fn=cmd_trials)

    ci = sub.add_parser("cins", help="look up missing CINs for review (network)")
    ci.add_argument("--limit", type=int, help="only the first N companies")
    ci.set_defaults(fn=cmd_cins)
    return p


def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("yfinance").disabled = True
    args = build_parser().parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
