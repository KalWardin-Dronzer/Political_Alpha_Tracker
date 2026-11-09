"""
List purchasers for the matching audit (data/match_audit.csv).

    python -m scripts.audit_candidates

Three groups of purchasers that the rules leave unattributed or doubtful:

1. the TOP_N largest unmatched purchasers by amount;
2. every unmatched purchaser whose name is close to a listed company's under
   looser rules (no leading-word rule, two scorers, score >= LOOSE_SCORE);
3. every purchaser the strict match rejected (failed leading word, or a
   normalised name two listed companies share).

Purchasers already in the audit are left out, so an empty list means every
candidate has a decision. Decisions, with a source for each, are written into
data/match_audit.csv by hand.
"""

import pandas as pd
from rapidfuzz import fuzz, process

from src.connections import attribute, load_match_audit, match_names, normalize
from src.data.bonds import load_bond_purchases
from src.data.companies import load_companies, load_donor_cins

TOP_N = 60
LOOSE_SCORE = 85


def candidates(bonds: pd.DataFrame, companies: pd.DataFrame, audit: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """(candidates not yet in the audit, share of unattributed money the TOP_N hold)."""
    found = attribute(bonds, companies, load_donor_cins(), audit, level="group")
    totals = bonds.groupby("purchaser")["amount"].agg(crore=lambda s: s.sum() / 1e7,
                                                      largest_lakh=lambda s: s.max() / 1e5)
    unmatched = totals[~totals.index.isin(set(found["purchaser"]))]

    choices = {}
    for _, c in companies.iterrows():
        choices.setdefault(normalize(c["name"]), f"{c['name']} ({c['nse_symbol']})")
    names = [n for n in choices if n]

    rows = []
    for purchaser, r in unmatched.iterrows():
        norm = normalize(purchaser)
        hits = [process.extractOne(norm, names, scorer=s) or ("", 0, 0)
                for s in (fuzz.token_sort_ratio, fuzz.token_set_ratio)] if norm else [("", 0, 0)]
        best = max(hits, key=lambda hit: hit[1])  # by score, not by name
        rows.append({"purchaser": purchaser, "crore": r["crore"], "largest_lakh": r["largest_lakh"],
                     "candidate": choices.get(best[0], ""), "score": round(best[1])})
    table = pd.DataFrame(rows).sort_values("crore", ascending=False).reset_index(drop=True)
    top = table.head(TOP_N).assign(why="top")
    loose = table[table["score"] >= LOOSE_SCORE].assign(why="close name")
    _, rejected = match_names(bonds["purchaser"].unique(), companies)
    rej = table[table["purchaser"].isin({r[0] for r in rejected})].assign(why="rejected")
    out = (pd.concat([top, loose, rej]).groupby("purchaser", as_index=False)
             .agg({"crore": "first", "largest_lakh": "first", "candidate": "first", "score": "first",
                   "why": lambda s: "+".join(sorted(set(s)))})
             .sort_values("crore", ascending=False))
    share = top["crore"].sum() / unmatched["crore"].sum()
    return out[~out["purchaser"].isin(set(audit["purchaser"]))], share


def main() -> int:
    bonds, companies, audit = load_bond_purchases(), load_companies(), load_match_audit()
    out, share = candidates(bonds, companies, audit)
    print(f"candidates without a decision: {len(out)} (the top {TOP_N} unattributed purchasers hold {share:.1%} "
          f"of the unattributed money)")
    pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_colwidth", 80)
    if len(out):
        print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
