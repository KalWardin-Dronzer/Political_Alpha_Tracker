"""
Which listed companies bought electoral bonds.

A bond is attributed to a listed company in one of three ways:

1. Name match. Both names are stripped of corporate boilerplate ("Limited",
   "India", "Industries" ...), a period between two letters is read as a space
   ("DR.REDDY'S" becomes "dr reddys") and spaced initials are joined ("J K
   Cement" becomes "jk cement"). The leading word must then match exactly, and
   RapidFuzz's token_sort_ratio must reach MATCH_THRESHOLD. The leading-word
   rule exists because a score alone cannot separate some unrelated companies:
   "GTL Infrastructure" and "GSL Infrastructure" score 94.
2. Donor CIN. data/donor_cins.csv maps 29 purchaser spellings to a listed
   company's CIN. It covers names the strict match misses, such as
   "DIVI S LABORATORIES" (leading word "divi", not "divis"),
   "TORRENT PHARMACEUTICALS" (listed as "Torrent Pharma") and
   "JINDAL STEEL AND POWER" (since renamed Jindal Steel).
3. Audit. data/match_audit.csv records a decision for every purchaser that was
   reviewed: the 60 largest unmatched purchasers by amount and every unmatched
   name close to a listed company's name under looser rules. It attributes
   spellings, former names and companies since merged into a listed one
   ("same_company"), and majority-owned subsidiaries of a listed company
   ("subsidiary"), each with a source; "not_attributed" overrides any match.

Two definitions of a connected company follow, set by `level`:

- "entity": the listed company bought bonds itself, under any spelling or
  former name;
- "group": also through a majority-owned subsidiary. It is the primary
  definition, because a company whose wholly owned subsidiary bought Rs 135
  crore of bonds is not an unconnected control.

A company counts as connected if any bond attributed to it is at least
MIN_BOND. Every bond counts, not only the last one seen for a company.
"""

import re

import pandas as pd
from rapidfuzz import fuzz, process

from src.config import ATTRIBUTION_LEVEL, MATCH_AUDIT_FILE, MATCH_THRESHOLD, MIN_BOND
from src.data.bonds import load_bond_purchases
from src.data.cin_resolver import _first_token, normalize as _strip_boilerplate
from src.data.companies import company_key, load_companies, load_donor_cins

_SPACED_INITIAL = re.compile(r"\b([a-z])\s+(?=[a-z]\b)")
_PERIOD_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z])\.(?=[A-Za-z])")

LEVELS = ("entity", "group")
DECISIONS = ("same_company", "subsidiary", "not_attributed")


def normalize(name: str) -> str:
    """Boilerplate-free, lower-case name with spaced initials joined: 'J K Cement Ltd' -> 'jk cement'."""
    spaced = _PERIOD_BETWEEN_LETTERS.sub(" ", str(name))
    return _SPACED_INITIAL.sub(r"\1", _strip_boilerplate(spaced))


def load_match_audit(path=MATCH_AUDIT_FILE) -> pd.DataFrame:
    """One row per reviewed purchaser spelling: decision, listed company, relation and source."""
    audit = pd.read_csv(path, dtype=str, keep_default_na=False)
    bad = sorted(set(audit["decision"]) - set(DECISIONS))
    if bad:
        raise ValueError(f"unknown audit decisions: {bad}")
    if audit["purchaser"].duplicated().any():
        raise ValueError("a purchaser appears twice in the audit")
    return audit


def match_names(donor_names, companies: pd.DataFrame, threshold: int = MATCH_THRESHOLD):
    """Map donor names to company keys by strict name match.

    Returns (matches, rejected): matches maps donor name -> company key, and
    rejected lists (donor name, best candidate, score) for candidates that
    cleared the score but failed the leading-word rule or named a normalised
    name that two listed companies share ("DCM Shriram" and "DCM Shriram
    Industries" both become "dcm shriram"; the audit resolves those).
    """
    keys: dict[str, set[str]] = {}
    for _, company in companies.iterrows():
        norm = normalize(company["name"])
        if norm:
            keys.setdefault(norm, set()).add(company_key(company))
    choices = list(keys)

    matches, rejected = {}, []
    for name in sorted(set(donor_names)):
        norm = normalize(name)
        if not norm:
            continue
        best = process.extractOne(norm, choices, scorer=fuzz.token_sort_ratio)
        if not best or best[1] < threshold:
            continue
        if _first_token(best[0]) != _first_token(norm) or len(keys[best[0]]) > 1:
            rejected.append((name, best[0], best[1]))
            continue
        matches[name] = next(iter(keys[best[0]]))
    return matches, rejected


def attribute(bonds: pd.DataFrame, companies: pd.DataFrame, donor_cins: dict[str, str],
              audit: pd.DataFrame = None, level: str = ATTRIBUTION_LEVEL) -> pd.DataFrame:
    """Bonds attributed to listed companies, one row per (bond, company).

    A purchaser in the audit is attributed by the audit alone, so an audit
    decision overrides the name match and the donor-CIN table.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    audit = pd.DataFrame(columns=["purchaser", "decision", "nse_symbol"]) if audit is None else audit
    audit = audit[audit["purchaser"].isin(set(bonds["purchaser"]))]
    reviewed = set(audit["purchaser"])

    matches, _ = match_names(bonds["purchaser"].unique(), companies)
    listed = set(companies.loc[companies["cin"] != "", "cin"])
    by_cin = {name: cin for name, cin in donor_cins.items() if cin in listed}

    by_symbol = dict(zip(companies["nse_symbol"], companies.apply(company_key, axis=1)))
    allowed = {"same_company"} | ({"subsidiary"} if level == "group" else set())
    used = audit[audit["decision"].isin(allowed)]
    unknown = sorted(set(used["nse_symbol"]) - set(by_symbol))
    if unknown:
        raise ValueError(f"audit names companies outside the universe: {unknown}")
    by_audit = {row.purchaser: by_symbol[row.nse_symbol] for row in used.itertuples()}
    route = {row.purchaser: "subsidiary" if row.decision == "subsidiary" else "audit" for row in used.itertuples()}

    bonds = bonds.reset_index(names="bond")
    rest = bonds[~bonds["purchaser"].isin(reviewed)]
    # Map on each frame's own column: assigning a longer Series to an empty frame would add rows.
    found = pd.concat([
        rest.assign(company=rest["purchaser"].map(matches), route="name"),
        rest.assign(company=rest["purchaser"].map(by_cin), route="cin"),
        bonds.assign(company=bonds["purchaser"].map(by_audit), route=bonds["purchaser"].map(route)),
    ])
    # A bond found by both routes for the same company counts once.
    return (found.dropna(subset=["company"])
                 .drop_duplicates(["bond", "company"])
                 .reset_index(drop=True))


def connections(bonds: pd.DataFrame = None, companies: pd.DataFrame = None,
                donor_cins: dict[str, str] = None, audit: pd.DataFrame = None,
                level: str = ATTRIBUTION_LEVEL) -> pd.DataFrame:
    """One row per listed company with bonds attributed to it, largest buyers first."""
    bonds = load_bond_purchases() if bonds is None else bonds
    companies = load_companies() if companies is None else companies
    donor_cins = load_donor_cins() if donor_cins is None else donor_cins
    audit = load_match_audit() if audit is None else audit

    found = attribute(bonds, companies, donor_cins, audit, level)
    by_company = found.groupby("company")
    via_subsidiary = found[found["route"] == "subsidiary"].groupby("company")["amount"].sum()
    table = pd.DataFrame({
        "bonds": by_company.size(),
        "total": by_company["amount"].sum(),
        "largest": by_company["amount"].max(),
        "first": by_company["date"].min(),
        "last": by_company["date"].max(),
        "purchasers": by_company["purchaser"].agg(lambda s: "; ".join(sorted(set(s)))),
    })
    table["via_subsidiary"] = via_subsidiary.reindex(table.index).fillna(0.0)
    table["connected"] = table["largest"] >= MIN_BOND

    info = (companies.assign(company=companies.apply(company_key, axis=1))
                     .drop_duplicates("company")
                     .set_index("company")[["name", "nse_symbol", "sector", "cin", "scrip_code"]])
    return table.join(info).sort_values("total", ascending=False)
