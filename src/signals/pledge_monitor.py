"""
Promoter Pledge Monitor

Reads BSE SAST disclosures about encumbered shares and alerts when a PROMOTER's
encumbrance genuinely falls at a company in the electoral-bond graph.

WHY THE DECISION NO LONGER BELONGS TO THE LLM
---------------------------------------------
On 2026-09-22 this monitor sent "INSIDER TELL: PROMOTER PLEDGE RELEASED" for
Patel Engineering. The filing behind it was a Regulation 29(2) disclosure by
Catalyst Trusteeship, debenture trustee for the company's lenders. It reported
a pledge released on 17 September and a non-disposal undertaking created on the
same 6.22% of capital the next day: net change nil, 26.31% encumbered before and
after, and "Whether the acquirer belongs to Promoter/Promoter group: No".

The old prompt told Gemini every filing was a promoter's Regulation 31
disclosure and allowed exactly one action per filing. So it returned "Released
6.22%" with the trustee as the "promoter", dropped the NDU leg, and this module
alerted on that without checking anything.

Gemini now only extracts figures. assess_disclosure() makes the decision from
facts it can check against the filing text:

  1. The before and after encumbrance must both be extracted AND printed in the
     filing. A figure the model worked out for itself (26.31 + 6.22 = 32.53)
     is refused.
  2. The change is after minus before, never the model's own number.
  3. Any legs the model lists must reconcile to that change.
  4. An invocation is never a release.
  5. The discloser must be in the promoter group, read from the filing's own
     "belongs to Promoter/Promoter group Yes/No" line, or implied by a
     Regulation 31 disclosure. When the filing does not say, it fails closed.
  6. The net release must be at least MIN_NET_RELEASE_PCT.

Whether promoter pledge releases predict returns has NOT been tested in this
project, and the alert says so.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.data.cache_manager import CacheManager
from src.execution.notifier import Notifier
from src.signals.graph_manager import GraphManager
from src.signals.alpha_engine import AlphaEngine
from src.config import ALPHA_SCORE_THRESHOLD

logger = logging.getLogger(__name__)

# Percentage points of total share capital.
MIN_NET_RELEASE_PCT = 2.0
# Extracted legs must sum to (after - before) within this many points.
RECONCILE_TOLERANCE = 0.05

BSE_ATTACHMENT_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{}"

# Regulation 29 forms carry "Whether the acquirer belongs to Promoter/Promoter
# group  Yes/No". PDF extraction can split it across lines.
_PROMOTER_FLAG_RE = re.compile(
    r"belongs?\s+to\s+(?:the\s+)?promoter\s*/?\s*promoter\s*group\W{0,20}?(yes|no)\b",
    re.IGNORECASE,
)
_REG29_RE = re.compile(r"\breg(?:ulation)?\.?\s*29\b", re.IGNORECASE)
_REG31_RE = re.compile(r"\breg(?:ulation)?\.?\s*31\b", re.IGNORECASE)
# Percentages as printed: 26.31, (6.22), 40.00. Integers count too, which makes
# the "is it printed" check weaker for round figures, never stricter.
_NUMBER_RE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d+)?(?!\d)")

# Leg type prefix -> direction of the encumbrance change.
_LEG_SIGNS = (
    ("creat", +1), ("ndu", +1), ("non-disposal", +1), ("non disposal", +1),
    ("other", +1), ("releas", -1), ("invok", -1),
)


@dataclass
class PledgeAssessment:
    """The decision for one disclosure, and the reason for it."""
    alert: bool
    reason: str
    discloser: str = ""
    role: str = "unknown"                    # promoter | non_promoter | unknown
    verified: bool = False                   # figures printed in the filing and reconciled
    before_pct: Optional[float] = None
    after_pct: Optional[float] = None
    net_release_pct: Optional[float] = None  # before - after; positive means encumbrance fell
    action_type: str = "Unknown"             # Released | Created | Unchanged | Invoked | Unknown


def _pct(value) -> Optional[float]:
    """A percentage from a number or a printed string such as '26.31%' or '(6.22)'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return abs(float(value))
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return abs(float(match.group())) if match else None


def _printed_in(text: str, value: float) -> bool:
    """True if the filing prints this percentage anywhere."""
    return any(abs(float(n) - value) < 0.005 for n in _NUMBER_RE.findall(text))


def _leg_sign(kind: str) -> Optional[int]:
    kind = kind.strip().lower()
    return next((sign for prefix, sign in _LEG_SIGNS if kind.startswith(prefix)), None)


def discloser_role(text: str) -> str:
    """'promoter', 'non_promoter' or 'unknown', from the filing text alone."""
    text = text or ""
    flag = _PROMOTER_FLAG_RE.search(text)
    if flag:
        return "promoter" if flag.group(1).lower() == "yes" else "non_promoter"
    # Regulation 31 is the promoter's own disclosure format.
    if _REG31_RE.search(text) and not _REG29_RE.search(text):
        return "promoter"
    return "unknown"


def assess_disclosure(text: str, extraction: dict) -> PledgeAssessment:
    """Decide whether one disclosure warrants an alert. Pure: no I/O, no LLM."""
    text = text or ""
    ex = extraction or {}
    before = _pct(ex.get("encumbered_pct_before"))
    after = _pct(ex.get("encumbered_pct_after"))
    legs = [leg for leg in (ex.get("legs") or []) if isinstance(leg, dict)]

    a = PledgeAssessment(
        alert=False, reason="",
        discloser=str(ex.get("discloser_name") or ex.get("promoter_name") or "").strip(),
        role=discloser_role(text), before_pct=before, after_pct=after,
    )

    if before is None or after is None:
        a.reason = ("before/after encumbrance not extracted, so the change "
                    "cannot be checked against the filing")
        return a

    change = after - before
    invoked = any(str(leg.get("type", "")).strip().lower().startswith("invok")
                  for leg in legs)
    a.net_release_pct = round(-change, 4)
    a.action_type = ("Invoked" if invoked else
                     "Released" if change < 0 else
                     "Created" if change > 0 else "Unchanged")

    for label, value in (("before", before), ("after", after)):
        if not _printed_in(text, value):
            a.reason = f"extracted {label} figure {value:.2f}% is not printed in the filing"
            return a

    if legs:
        signed = 0.0
        for leg in legs:
            sign, size = _leg_sign(str(leg.get("type", ""))), _pct(leg.get("pct"))
            if sign is None or size is None:
                a.reason = f"unrecognised leg {leg!r}"
                return a
            signed += sign * size
        if abs(change - signed) > RECONCILE_TOLERANCE:
            a.reason = (f"legs sum to {signed:+.2f} pp but the encumbrance moved "
                        f"{change:+.2f} pp")
            return a

    a.verified = True

    if invoked:
        a.reason = "invocation: lenders enforced the pledge, which is not a release"
        return a
    if a.role != "promoter":
        a.reason = ("discloser is not in the promoter group" if a.role == "non_promoter"
                    else "the filing does not show whether the discloser is a promoter")
        return a
    if a.net_release_pct < MIN_NET_RELEASE_PCT:
        a.reason = (f"encumbrance moved {change:+.2f} pp; an alert needs a net "
                    f"release of at least {MIN_NET_RELEASE_PCT:.1f} pp")
        return a

    a.alert = True
    a.reason = f"promoter encumbrance fell from {before:.2f}% to {after:.2f}%"
    return a


class PledgeMonitor:
    def __init__(self, cache: CacheManager, notifier: Notifier, graph: GraphManager, alpha_engine: AlphaEngine):
        self.cache = cache
        self.notifier = notifier
        self.graph = graph
        self.alpha_engine = alpha_engine

    def process_pledge_events(self, events: list) -> int:
        """
        Assess each disclosure and alert where assess_disclosure() allows it and
        the company is in the electoral-bond graph.

        Returns the number of alerts sent so the daily funnel can count them. It
        used to return nothing, and the 2026-09-22 summary said "Alerts Fired: 0"
        four minutes after this monitor had sent an alert.
        """
        logger.info(f"Processing {len(events)} Promoter Pledge events...")
        sent = 0

        for e in events:
            raw = e.raw_data or {}
            pdf_path = raw.get("pdf_path")
            text = self.alpha_engine.extract_text_from_pdf(pdf_path) if pdf_path else e.title
            if not text:
                continue

            extraction = self.alpha_engine.analyze_pledge_document(text)
            if not extraction:
                continue

            verdict = assess_disclosure(text, extraction)
            logger.info(f"  Pledge {e.scrip_code} {e.date}: {verdict.action_type}, "
                        f"{'ALERT' if verdict.alert else 'no alert'} ({verdict.reason})")

            # Only verified promoter figures are stored: alpha_engine reads the
            # latest total_pledged_pct as the promoter's pledge level and blocks
            # contract alerts at 25%, so a trustee's holding or a placeholder
            # would silently change contract scoring.
            if not (verdict.verified and verdict.role == "promoter"):
                continue
            if not self._record(e, verdict):
                continue  # already processed
            if not verdict.alert:
                continue

            company = self.cache.get_company(e.scrip_code)
            cin = company.get("cin") if company else None
            if not cin:
                continue
            connections = self.graph.alpha_query(cin)
            if not connections or connections[0]["alpha_score"] < ALPHA_SCORE_THRESHOLD:
                continue

            if self._send_pledge_alert(company, verdict, connections[0],
                                       raw.get("ATTACHMENTNAME")):
                sent += 1

        return sent

    def _record(self, e, verdict: PledgeAssessment) -> bool:
        """Store a verified promoter disclosure. False if it was already processed."""
        with self.cache._connect() as conn:
            exists = conn.execute(
                "SELECT id FROM pledges WHERE scrip_code = ? AND date = ? AND action_type = ?",
                (e.scrip_code, e.date, verdict.action_type)
            ).fetchone()
        if exists:
            return False

        try:
            with self.cache._connect() as conn:
                conn.execute("""
                    INSERT INTO pledges (scrip_code, promoter_name, action_type, pct_change, total_pledged_pct, date, processed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    e.scrip_code, verdict.discloser or "Promoter Group", verdict.action_type,
                    abs(verdict.net_release_pct), verdict.after_pct,
                    e.date, datetime.now().isoformat()
                ))
        except Exception as db_e:
            logger.warning(f"Could not save pledge to db, maybe table missing? Error: {db_e}")
        return True

    def _send_pledge_alert(self, company: dict, verdict: PledgeAssessment,
                           connection: dict, attachment: Optional[str] = None) -> bool:
        """Send a factual alert. Every interpolated name is escaped for Telegram HTML."""
        esc = html.escape
        lines = [
            "🔓 <b>PROMOTER PLEDGE RELEASE</b>",
            "",
            f"<b>Company:</b> {esc(str(company['name']))} (BSE: {esc(str(company['scrip_code']))})",
            f"<b>Disclosed by:</b> {esc(verdict.discloser or 'not stated')}",
            f"<b>Encumbered:</b> {verdict.before_pct:.2f}% → {verdict.after_pct:.2f}% "
            f"(net release {verdict.net_release_pct:.2f} pp of total capital)",
        ]
        if attachment:
            url = esc(BSE_ATTACHMENT_URL.format(attachment), quote=True)
            lines.append(f'<b>Filing:</b> <a href="{url}">BSE disclosure</a>')
        lines += [
            "",
            "<i>Untested: this project has not measured whether pledge releases "
            "predict returns. Read the filing before acting on this.</i>",
            "",
            "🕸️ <b>Electoral-bond link:</b>",
            f"• Score: {connection['alpha_score']:.2f}",
        ]
        director = connection.get("director_name")
        if director == "DIRECT_DONOR":
            lines.append("• Path: the company itself appears as a bond purchaser")
        elif director:
            lines.append(f"• Via director: {esc(str(director))}")
        lines.append(f"• Donor: {esc(str(connection.get('donor_company_name', '')))}")
        if connection.get("is_bureaucrat"):
            lines.append(f"• {esc(str(director or 'The director'))} is flagged as a former bureaucrat")

        return bool(self.notifier._send_message("\n".join(lines)))
