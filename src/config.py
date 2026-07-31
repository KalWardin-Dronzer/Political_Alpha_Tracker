"""
Political Alpha Tracker — Central Configuration

All constants, thresholds, regex patterns, API URLs, and tunable parameters
live here. Modules import from this file instead of hardcoding values.
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GRAPH_FILE = DATA_DIR / "graph.json"
CACHE_DB = DATA_DIR / "cache.sqlite"
HELD_POSITIONS_FILE = DATA_DIR / "held_positions.csv"
ELECTORAL_BONDS_PURCHASE_FILE = DATA_DIR / "PurchaseData.csv"
ELECTORAL_BONDS_ENCASHMENT_FILE = DATA_DIR / "EncashmentData.csv"
NSE_INDUSTRY_FILE = DATA_DIR / "nse_industry_mapping.csv"

# ──────────────────────────────────────────────
# Telegram
# ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ──────────────────────────────────────────────
# Cache TTLs (days)
# ──────────────────────────────────────────────
MCA_CACHE_TTL_DAYS = int(os.getenv("MCA_CACHE_TTL_DAYS", "90"))
MARKET_CAP_CACHE_TTL_DAYS = int(os.getenv("MARKET_CAP_CACHE_TTL_DAYS", "7"))
ANNOUNCEMENT_LOOKBACK_DAYS = int(os.getenv("ANNOUNCEMENT_LOOKBACK_DAYS", "365"))
HELD_POSITION_EXPIRY_DAYS = 180

# ──────────────────────────────────────────────
# Watchlist Generation — Sector Keywords
# ──────────────────────────────────────────────
# These are matched (case-insensitive, partial) against NSE industry classification.
# Sectors that are heavily government-dependent or subsidy-driven.
GOVT_DEPENDENT_SECTORS = [
    # Defence & Aerospace
    "defence", "aerospace", "shipbuilding",
    # Railways
    "railway", "rail equipment", "locomotive", "metro",
    # Power & Energy
    "power generation", "power transmission", "power distribution",
    "electrical equipment", "transformer", "switchgear",
    "renewable energy", "solar", "wind energy",
    # Infrastructure & Construction
    "road", "highway", "bridge", "tunnel",
    "construction", "infrastructure",
    "water treatment", "irrigation", "water supply",
    "smart city", "urban development",
    # Smart Meters & AMI
    "smart meter", "metering", "ami",
    # IT — Government
    "e-governance", "government it",
    # Mining & Steel (PSU-heavy)
    "mining", "coal",
]

# ──────────────────────────────────────────────
# BSE Announcement Regex Patterns
# ──────────────────────────────────────────────
CONTRACT_KEYWORDS_PATTERN = re.compile(
    r"(?i)\b("
    r"award\s*(of)?\s*(order|contract|work)?"
    r"|order\s*(received|won|bagged|secured)"
    r"|(received|won|bagged|secured)\s+order"
    r"|tender\s*(award|won)"
    r"|letter\s*of\s*(acceptance|award|intent|LOA)"
    r"|LOA\s*(received)?"
    r"|contract\s*(award|won|received|secured|bagged)"
    r"|work\s*order\s*(received|won)?"
    r"|new\s*order"
    r"|order\s*book"
    r"|EPC\s*(contract|order)"
    r"|supply\s*order"
    r"|order\s*worth"
    r")\b"
)

BOARD_CHANGE_PATTERN = re.compile(
    r"(?i)\b("
    r"appointment\s+(of|as)\s+.*?director"
    r"|resignation\s+(of|from)\s+.*?director"
    r"|cessation\s+(of|from)\s+.*?director"
    r"|change\s+in\s+(directors?|board\s*composition|KMP)"
    r"|appointment|resignation|cessation"
    r"|key\s*managerial\s*personnel|KMP"
    r")\b"
)

# Pattern to exclude false positives (e.g., "Order of NCLT")
CONTRACT_EXCLUSION_PATTERN = re.compile(
    r"(?i)\b(NCLT|NCLAT|SAT|SEBI\s*order|court\s*order|regulatory)\b"
)

# ──────────────────────────────────────────────
# Fundamental Thresholds (The Porinju Layer)
# ──────────────────────────────────────────────
MAX_DEBT_TO_EQUITY = 5.0  # Loosened to include more leveraged companies
MAX_PROMOTER_PLEDGE_PCT = 50.0  # Absolute max
MIN_OPERATING_CASHFLOW = 0  # Must be non-negative at least once in last 2 years
MARKET_CAP_MIN_CR = 50  # Rs.50 Crore minimum (too small = illiquid)
MARKET_CAP_MAX_CR = 1000000  # Rs.10,00,000 Crore maximum (includes large-caps)
MIN_CONTRACT_FREQUENCY = 1  # Minimum contract announcements in lookback period

# ──────────────────────────────────────────────
# Donor Match Thresholds
# ──────────────────────────────────────────────
DONOR_MIN_AMOUNT_CR = 10  # Rs.10 Crore minimum donation to qualify for watchlist
DONOR_MATCH_SCORE = 75  # Fuzzy match threshold for donor-company name matching

# ──────────────────────────────────────────────
# BSE API Configuration
# ──────────────────────────────────────────────
BSE_BASE_URL = "https://api.bseindia.com/BseIndiaAPI/api"
BSE_ANNOUNCEMENTS_URL = f"{BSE_BASE_URL}/AnnSubCategoryGetData/w"
BSE_CORP_INFO_URL = f"{BSE_BASE_URL}/CorporateAction/w"
BSE_SCRIP_LIST_URL = "https://www.bseindia.com/corporates/List_Scrips.html"

BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
}

BSE_REQUEST_DELAY = 1.0  # seconds between requests

# ──────────────────────────────────────────────
# MCA Configuration
# ──────────────────────────────────────────────
MCA_COMPANY_SEARCH_URL = "https://www.mca.gov.in/mcafoportal/companyLLPMasterData.do"
MCA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
MCA_REQUEST_DELAY = 2.0  # seconds between requests

# ──────────────────────────────────────────────
# Zaubacorp Configuration (Director Data Fallback)
# ──────────────────────────────────────────────
ZAUBACORP_BASE_URL = "https://www.zaubacorp.com/company"
ZAUBACORP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
ZAUBACORP_REQUEST_DELAY = 2.0  # seconds between requests (be respectful)

# ──────────────────────────────────────────────
# Electoral Trust / Donor Configuration
# ──────────────────────────────────────────────
# MyNeta URLs for electoral trust data
MYNETA_TRUST_URL = "https://www.myneta.info/party/index.php?action=electoral_trusts"
ECI_TRUST_URL = "https://www.eci.gov.in/electoral-trusts"

DONATION_RECENCY_YEARS = 10  # Cover all Electoral Bonds history (banned in 2024)
DONATION_MIN_AMOUNT_LAKHS = 10  # Minimum ₹10 lakh to filter noise
DONATION_MIN_AMOUNT = DONATION_MIN_AMOUNT_LAKHS * 100_000  # In rupees

# ──────────────────────────────────────────────
# Alpha Query Scoring Weights
# ──────────────────────────────────────────────
ALPHA_WEIGHT_EXCLUSIVITY = 0.4  # Director board seat exclusivity
ALPHA_WEIGHT_PROXIMITY = 0.3  # Path length (fewer hops = stronger)
ALPHA_WEIGHT_MAGNITUDE = 0.3  # Donation size
ALPHA_SCORE_THRESHOLD = 0.5  # Minimum score to fire alert
MAX_PATH_HOPS = 3  # Maximum graph traversal depth

# ──────────────────────────────────────────────
# Rate Limiting
# ──────────────────────────────────────────────
YFINANCE_REQUEST_DELAY = 0.5  # seconds between yfinance calls
MYNETA_REQUEST_DELAY = 1.5  # seconds between MyNeta requests

# ──────────────────────────────────────────────
# Backtest Configuration
# ──────────────────────────────────────────────
BACKTEST_WINDOWS_DAYS = [30, 60, 90, 180, 360]
BACKTEST_BENCHMARK = "BSE-SMLCAP"  # BSE SmallCap Index
MIN_WIN_RATE = 0.55  # 55% win rate threshold

# ──────────────────────────────────────────────
# Graph Pruning
# ──────────────────────────────────────────────
TENDER_MAX_AGE_MONTHS = 24  # Remove tenders older than 2 years
DONOR_MAX_AGE_YEARS = 5  # Remove donations older than 5 years

# ──────────────────────────────────────────────
# State vs Central Mapping (Phase 2)
# ──────────────────────────────────────────────
STATE_PARTY_MAPPING = {
    "telangana": ["bharat rashtra samithi", "trs", "brs"],
    "west bengal": ["all india trinamool congress", "tmc", "trinamool"],
    "tamil nadu": ["dravida munnetra kazhagam", "dmk", "aiadmk"],
    "odisha": ["biju janata dal", "bjd"],
    "andhra pradesh": ["yuvajana sramika rythu congress party", "ysrcp", "telugu desam party", "tdp"],
    "maharashtra": ["shiv sena", "ncp", "nationalist congress party"],
    "bihar": ["janata dal (united)", "jdu", "rashtriya janata dal", "rjd"],
    "karnataka": ["janata dal (secular)", "jds", "inc", "bjp"],
    "central": ["bharatiya janata party", "bjp", "indian national congress", "inc"],
    # Default to broad matches for pan-India parties
    "unknown": ["bharatiya janata party", "bjp", "indian national congress", "inc"]
}

# ──────────────────────────────────────────────
# Election Cycle Weighting (Phase 5)
# ──────────────────────────────────────────────
ELECTION_MULTIPLIER = 1.5  # Boost alpha score by 50% if election is within 12 months
UPCOMING_ELECTIONS = {
    # State: (Year, Month)
    "maharashtra": (2024, 10),
    "haryana": (2024, 10),
    "jharkhand": (2024, 11),
    "delhi": (2025, 2),
    "bihar": (2025, 10),
    "west bengal": (2026, 4),
    "tamil nadu": (2026, 4),
    "central": (2029, 4), # Next Lok Sabha
}
