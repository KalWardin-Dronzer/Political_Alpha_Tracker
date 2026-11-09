"""
Paths and the rules that decide which companies count as politically connected.

Everything a published number depends on is fixed here, so a result does not
drift with the calendar or with whoever runs it.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"

# Inputs, all committed (see data/README.md for where each came from).
COMPANIES_FILE = DATA_DIR / "companies.csv"
BOND_PURCHASES_FILE = DATA_DIR / "PurchaseData.csv"
DONOR_CINS_FILE = DATA_DIR / "donor_cins.csv"
MATCH_AUDIT_FILE = DATA_DIR / "match_audit.csv"

# Which purchases make a listed company "connected": "entity" counts only bonds
# the company bought itself; "group" also counts bonds bought by its
# majority-owned subsidiaries (data/match_audit.csv, each with a source). Group
# is the primary definition; every study also reports entity as a check.
ATTRIBUTION_LEVEL = "group"

# Donor-to-company name matching. Names are stripped of corporate boilerplate,
# the leading word must match exactly, and RapidFuzz's token_sort_ratio must
# reach this score. Token-overlap scorers at lower thresholds paired unrelated
# companies that share words like "International" or "Infrastructure".
MATCH_THRESHOLD = 93

# A company counts as connected if it bought at least one bond of this
# denomination or larger: Rs 10 lakh. Bonds were sold in Rs 1,000, 10,000,
# 1 lakh, 10 lakh and 1 crore denominations.
MIN_BOND = 1_000_000

# Price panel end date (exclusive). The panel ends on 10 September 2026, the day
# the first 1,588 symbols were downloaded; symbols added later are fetched to the
# same date, so every study sees one calendar.
PRICE_END = "2026-09-11"
