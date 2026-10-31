"""
Which listed companies bought electoral bonds.

A bond is attributed to a listed company in one of two ways:

1. Name match. Both names are stripped of corporate boilerplate ("Limited",
   "India", "Industries" ...) and spaced initials are joined ("J K Cement"
   becomes "jk cement"). The leading word must then match exactly, and
   RapidFuzz's token_sort_ratio must reach MATCH_THRESHOLD. The leading-word
   rule exists because a score alone cannot separate some unrelated companies:
   "GTL Infrastructure" and "GSL Infrastructure" score 94.
2. Donor CIN. data/donor_cins.csv maps 29 purchaser spellings to a listed
   company's CIN. It covers names the strict match misses, such as
   "DIVI S LABORATORIES" (leading word "divi", not "divis"),
   "TORRENT PHARMACEUTICALS" (listed as "Torrent Pharma") and
   "JINDAL STEEL AND POWER" (since renamed Jindal Steel).

A company counts as connected if any bond attributed to it is at least
MIN_BOND. Every bond counts, not only the last one seen for a company.
"""

import re

import pandas as pd
from rapidfuzz import fuzz, process

from src.config import MATCH_THRESHOLD, MIN_BOND
from src.data.bonds import load_bond_purchases
from src.data.cin_resolver import _first_token, normalize as _strip_boilerplate
from src.data.companies import company_key, load_companies, load_donor_cins

_SPACED_INITIAL = re.compile(r"\b([a-z])\s+(?=[a-z]\b)")


def normalize(name: str) -> str:
    """Boilerplate-free, lower-case name with spaced initials joined: 'J K Cement Ltd' -> 'jk cement'."""
    return _SPACED_INITIAL.sub(r"\1", _strip_boilerplate(name))


def match_names(donor_names, companies: pd.DataFrame, threshold: int = MATCH_THRESHOLD):
    """Map donor names to company keys by strict name match.

    Returns (matches, rejected): matches maps donor name -> company key, and
    rejected lists (donor name, best candidate, score) for candidates that
    cleared the score but failed the leading-word rule.
    """
    choices, keys = [], {}
    for _, company in companies.iterrows():
        norm = normalize(company["name"])
        if norm:
            choices.append(norm)
            keys[norm] = company_key(company)

    matches, rejected = {}, []
    for name in sorted(set(donor_names)):
        norm = normalize(name)
        if not norm:
            continue
        best = process.extractOne(norm, choices, scorer=fuzz.token_sort_ratio)
        if not best or best[1] < threshold:
            continue
        if _first_token(best[0]) != _first_token(norm):
            rejected.append((name, best[0], best[1]))
            continue
        matches[name] = keys[best[0]]
    return matches, rejected


def attribute(bonds: pd.DataFrame, companies: pd.DataFrame,
              donor_cins: dict[str, str]) -> pd.DataFrame:
    """Bonds attributed to listed companies, one row per (bond, company)."""
    matches, _ = match_names(bonds["purchaser"].unique(), companies)
    listed = set(companies.loc[companies["cin"] != "", "cin"])
    by_cin = {name: cin for name, cin in donor_cins.items() if cin in listed}

    bonds = bonds.reset_index(names="bond")
    found = pd.concat([
        bonds.assign(company=bonds["purchaser"].map(matches), route="name"),
        bonds.assign(company=bonds["purchaser"].map(by_cin), route="cin"),
    ])
    # A bond found by both routes for the same company counts once.
    return (found.dropna(subset=["company"])
                 .drop_duplicates(["bond", "company"])
                 .reset_index(drop=True))


def connections(bonds: pd.DataFrame = None, companies: pd.DataFrame = None,
                donor_cins: dict[str, str] = None) -> pd.DataFrame:
    """One row per listed company with bonds attributed to it, largest buyers first."""
    bonds = load_bond_purchases() if bonds is None else bonds
    companies = load_companies() if companies is None else companies
    donor_cins = load_donor_cins() if donor_cins is None else donor_cins

    found = attribute(bonds, companies, donor_cins)
    by_company = found.groupby("company")
    table = pd.DataFrame({
        "bonds": by_company.size(),
        "total": by_company["amount"].sum(),
        "largest": by_company["amount"].max(),
        "first": by_company["date"].min(),
        "last": by_company["date"].max(),
        "purchasers": by_company["purchaser"].agg(lambda s: "; ".join(sorted(set(s)))),
    })
    table["connected"] = table["largest"] >= MIN_BOND

    info = (companies.assign(company=companies.apply(company_key, axis=1))
                     .drop_duplicates("company")
                     .set_index("company")[["name", "nse_symbol", "sector", "cin", "scrip_code"]])
    return table.join(info).sort_values("total", ascending=False)


def connected_keys(table: pd.DataFrame = None) -> set[str]:
    """Keys of the companies that count as connected."""
    table = connections() if table is None else table
    return set(table.index[table["connected"]])
