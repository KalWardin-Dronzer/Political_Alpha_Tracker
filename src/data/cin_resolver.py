"""
Political Alpha Tracker — Name to CIN Resolver

WHY THIS MODULE HAD TO BE WRITTEN
---------------------------------
Nothing in this project could obtain a CIN. That was not obvious:
EntityResolver.resolve_company_cin() looks like a resolver, but its index is
built only from companies that ALREADY have a CIN --

    for c in companies:
        if normalized and c.get("cin"):      # <- only pre-existing CINs
            self._company_name_index[normalized] = c

-- so it can only ever return one of the 48 CINs already on file, and its fuzzy
branch could return the WRONG company's CIN for an unresolved name. Meanwhile
MCAResolver consumes a CIN to fetch directors, and WatchlistGenerator carries a
hardcoded ten-entry PSU dictionary. UniverseManager inserts cin="".

That is why CIN coverage sat at 48/1589 (3%), which in turn capped the political
graph at 20 connected companies and left every test of the political hypothesis
underpowered.

THE SOURCE
----------
Zaubacorp's company search, already scraped elsewhere in this project for
director data. Its result list pairs each company name with its CIN in the link
href, so a match can be verified by NAME rather than by taking whatever came
back first.

TWO THINGS MAKE THIS TRACTABLE
------------------------------
1. A listed company's CIN always begins with "L"; unlisted ones begin with "U".
   Since every company in this universe is listed, the L-prefix filter discards
   the millions of private companies that would otherwise dominate a name
   search.

2. Candidates are scored by fuzzy name similarity and rejected below a
   threshold. A wrong CIN is worse than no CIN: it would silently attach
   another company's directors to the graph and manufacture a political
   connection that does not exist. This resolver returns None rather than a
   guess.
"""

import html
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.zaubacorp.com/companysearchresults/{query}"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

# <a href="https://www.zaubacorp.com/NAME-SLUG-L00305MH1973PLC174201">NAME</a>
_RESULT_RE = re.compile(
    r'<a\s+href="https://www\.zaubacorp\.com/[^"]*?'
    r'([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})"[^>]*>([^<]+)</a>',
    re.I,
)

CIN_RE = re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")

# Below this name-similarity score the match is refused. A wrong CIN corrupts
# the graph silently; a missing one merely leaves a gap that is visible.
MATCH_THRESHOLD = 88

REQUEST_DELAY_SEC = 1.2

_NOISE = re.compile(
    r"\b(limited|ltd|private|pvt|public|company|co|corporation|corp|"
    r"industries|india|indian)\b",
    re.I,
)


@dataclass
class CinMatch:
    query: str
    cin: Optional[str]
    matched_name: Optional[str]
    score: float
    n_candidates: int
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.cin is not None


def normalize(name: str) -> str:
    """
    Strip corporate boilerplate so 'X Industries Ltd' matches 'X Industries Limited'.

    Apostrophes and periods are DELETED, not spaced: "Divi's" must become
    "divis" to line up with the registered name Zaubacorp returns. Spacing them
    would give "divi s", whose first token no longer matches and which the
    first-token guard below would then reject.
    """
    if not name:
        return ""
    # Unescape HTML entities here, not only at the scrape boundary: the
    # first-token guard compares normalized strings, so an entity that survives
    # to this point ("DIVI&#39;S" -> "divi 39 s") silently rejects a correct
    # match. Doing it in normalize() makes the comparison safe whatever the
    # source of the name.
    s = html.unescape(str(name)).lower()
    s = re.sub(r"[‘’'´`.]", "", s)      # delete, do not space
    s = re.sub(r"[^\w\s]", " ", s)
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _first_token(normalized: str) -> str:
    parts = normalized.split()
    return parts[0] if parts else ""


class CinResolver:
    """
        r = CinResolver()
        m = r.resolve("Alkem Laboratories Limited")
        m.cin  -> 'L00305MH1973PLC174201'
    """

    def __init__(self, session: requests.Session = None,
                 delay: float = REQUEST_DELAY_SEC,
                 threshold: int = MATCH_THRESHOLD,
                 listed_only: bool = True):
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        self.delay = delay
        self.threshold = threshold
        self.listed_only = listed_only
        self._last_request = 0.0

    def _throttle(self):
        gap = time.monotonic() - self._last_request
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last_request = time.monotonic()

    def _search(self, name: str, timeout: int = 25) -> list[tuple[str, str]]:
        """Return [(cin, name), ...] candidates for a company name."""
        self._throttle()
        url = SEARCH_URL.format(query=requests.utils.quote(name))
        try:
            resp = self.session.get(url, timeout=timeout)
        except Exception as e:
            logger.debug(f"search failed for {name!r}: {e}")
            return []
        if resp.status_code != 200:
            logger.debug(f"search HTTP {resp.status_code} for {name!r}")
            return []

        out, seen = [], set()
        for cin, cand in _RESULT_RE.findall(resp.text):
            cin = cin.upper()
            if cin in seen:
                continue
            seen.add(cin)
            # Zaubacorp HTML-escapes names: "DIVI&#39;S LABORATORIES LIMITED".
            # Without unescaping, normalize() turns that into
            # "divi 39 s laboratories" whose leading token is "divi", and the
            # first-token guard then rejects a perfectly correct match.
            out.append((cin, html.unescape(cand).strip()))
        return out

    @staticmethod
    def query_variants(name: str) -> list[str]:
        """
        Progressively looser search strings for one company.

        Zaubacorp's search matches literally, not fuzzily, so the exact
        registered name has to be hit fairly closely. Measured behaviour:

            "Britannia Industries Limited" -> 0 records
            "Britannia Industries"         -> 1 record   (correct)
            "Divi's Laboratories Limited"  -> 0 records
            "Divis Laboratories"           -> 4 records  (correct)

        So an apostrophe must be DELETED rather than turned into a space, and
        the "Limited" suffix is often better dropped. Variants are tried in
        order and the first one returning candidates wins; name verification
        still guards every result, so a looser query cannot produce a wrong CIN.
        """
        raw = str(name).strip()
        # Delete apostrophes and periods outright: "Divi's" -> "Divis".
        tight = re.sub(r"[''´`.]", "", raw)
        # Other punctuation becomes a space.
        tight = re.sub(r"[^\w\s&]", " ", tight)
        tight = re.sub(r"\s+", " ", tight).strip()

        no_suffix = re.sub(r"\s+(limited|ltd|corporation|corp)\s*$", "", tight, flags=re.I).strip()
        words = no_suffix.split()

        out = [raw, tight, no_suffix]
        if len(words) > 2:
            out.append(" ".join(words[:2]))
        if len(words) > 1:
            out.append(words[0])

        seen, uniq = set(), []
        for v in out:
            if v and len(v) >= 3 and v.lower() not in seen:
                seen.add(v.lower())
                uniq.append(v)
        return uniq

    def resolve(self, company_name: str) -> CinMatch:
        """
        Resolve one company name to a CIN, or return an unresolved CinMatch.

        Never guesses: below the similarity threshold it reports why it refused.
        """
        if not company_name or not str(company_name).strip():
            return CinMatch(company_name, None, None, 0.0, 0, "empty name")

        candidates, tried = [], 0
        for variant in self.query_variants(company_name):
            tried += 1
            candidates = self._search(variant)
            if candidates:
                break
        if not candidates:
            return CinMatch(company_name, None, None, 0.0, 0,
                            f"no search results after {tried} query variants")

        if self.listed_only:
            listed = [(c, n) for c, n in candidates if c.startswith("L")]
            if not listed:
                return CinMatch(company_name, None, None, 0.0, len(candidates),
                                f"no listed (L-prefix) CIN among {len(candidates)} results")
            candidates = listed

        target = normalize(company_name)
        target_head = _first_token(target)

        # The first token must match EXACTLY, on top of the score threshold.
        #
        # Fuzzy ratio alone is not safe here: "gtl infrastructure" vs
        # "gsl infrastructure" scores 94 — above any threshold that still admits
        # a genuine match like "divis laboratories" at 93 — yet GTL and GSL are
        # unrelated companies. One letter in a short acronym is a different firm,
        # and a wrong CIN would attach its directors to the graph silently.
        # Legitimate matches essentially always share their leading word.
        best_cin = best_name = None
        best_score = -1.0
        head_rejected = 0
        for cin, cand in candidates:
            cand_norm = normalize(cand)
            if target_head and _first_token(cand_norm) != target_head:
                head_rejected += 1
                continue
            score = fuzz.token_sort_ratio(target, cand_norm)
            if score > best_score:
                best_cin, best_name, best_score = cin, cand, score

        if best_cin is None:
            return CinMatch(company_name, None, None, 0.0, len(candidates),
                            f"no candidate shares the leading word "
                            f"{target_head!r} ({head_rejected} rejected)")

        if best_score < self.threshold:
            return CinMatch(company_name, None, best_name, best_score, len(candidates),
                            f"best score {best_score:.0f} below threshold {self.threshold}")

        return CinMatch(company_name, best_cin, best_name, best_score,
                        len(candidates), "matched")

    def resolve_batch(self, names: list[str]) -> list[CinMatch]:
        out = []
        for i, n in enumerate(names, 1):
            m = self.resolve(n)
            out.append(m)
            if i % 25 == 0:
                got = sum(1 for x in out if x.resolved)
                logger.info(f"  resolved {got}/{i}")
        return out
