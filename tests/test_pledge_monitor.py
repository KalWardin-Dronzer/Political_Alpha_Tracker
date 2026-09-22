"""
Regression tests for the promoter pledge monitor.

On 2026-09-22 the monitor sent "INSIDER TELL: PROMOTER PLEDGE RELEASED" for
Patel Engineering. The filing behind it, kept here as a fixture, is a
Regulation 29(2) disclosure by the lenders' debenture trustee. It reports a
pledge released and a non-disposal undertaking created on the same 6.22% of
capital: net change nil, 26.31% encumbered before and after, and the discloser
is not in the promoter group. Nothing was released.

The property under test is REFUSAL. An alert may fire only when the figures are
printed in the filing, reconcile, belong to a promoter, and show a real net
release. Gemini is stubbed throughout; the suite never calls it.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.signals.pledge_monitor import (
    MIN_NET_RELEASE_PCT,
    PledgeMonitor,
    assess_disclosure,
    discloser_role,
)

FIXTURE = (Path(__file__).parent / "fixtures"
           / "bse_sast_29_2_patel_engineering_2026-09-22.txt")
SEP22_TEXT = FIXTURE.read_text(encoding="utf-8")
SEP22_ATTACHMENT = "9B7B49DC_8BB3_4A91_AA90_2CEDA7AFA44F_115833.pdf"

# What the old prompt returned for that filing, reconstructed from the alert it
# produced. This is the input that fired.
SEP22_OLD_EXTRACTION = {
    "action_type": "Released",
    "pct_change": 6.22,
    "total_pledged_pct": 26.31,
    "promoter_name": "Catalyst Trusteeship Limited",
}

# A correct reading of the same filing under the new prompt.
SEP22_CORRECT_EXTRACTION = {
    "discloser_name": "Catalyst Trusteeship Limited",
    "encumbered_pct_before": 26.31,
    "encumbered_pct_after": 26.31,
    "legs": [{"type": "Released", "pct": 6.22}, {"type": "NDU", "pct": 6.22}],
}

# Synthetic promoter disclosure in the Regulation 31 format: a genuine release.
REG31_RELEASE_TEXT = """\
Format for disclosure by the Promoter(s) to the stock exchanges and to the Target
Company for encumbrance of shares / invocation of encumbrance / release of
encumbrance, in terms of Regulation 31(1) and 31(2) of SEBI (Substantial
Acquisition of Shares and Takeovers) Regulations, 2011
Name of the Target Company (TC): Example Infra Limited
Name of the promoter or PAC on whose shares encumbrance has been released:
Example Holdings Private Limited
Promoter holding already encumbered: 4,00,00,000 40.00
Details of events pertaining to encumbrance: Release of pledge 1,00,00,000 10.00
Post event holding of encumbered shares: 3,00,00,000 30.00
"""

REG31_RELEASE_EXTRACTION = {
    "discloser_name": "Example Holdings Private Limited",
    "encumbered_pct_before": 40.0,
    "encumbered_pct_after": 30.0,
    "legs": [{"type": "Released", "pct": 10.0}],
}


def as_promoter(text: str) -> str:
    """The Sep 22 filing, but with the discloser declared as promoter group."""
    flipped = text.replace("Promoter/Promoter group No", "Promoter/Promoter group Yes")
    assert flipped != text, "fixture no longer contains the promoter-group line"
    return flipped


class TestDiscloserRole:
    def test_sep22_filing_declares_a_non_promoter(self):
        assert discloser_role(SEP22_TEXT) == "non_promoter"

    def test_flag_survives_line_breaks(self):
        text = "Whether the acquirer belongs to Promoter/\nPromoter group\n  Yes"
        assert discloser_role(text) == "promoter"

    def test_regulation_31_format_is_a_promoter_disclosure(self):
        assert discloser_role(REG31_RELEASE_TEXT) == "promoter"

    def test_no_evidence_is_unknown(self):
        assert discloser_role("Disclosure of encumbered shares") == "unknown"


class TestAssessDisclosure:
    def test_the_extraction_that_fired_on_sep22_is_refused(self):
        a = assess_disclosure(SEP22_TEXT, SEP22_OLD_EXTRACTION)
        assert not a.alert
        assert "not extracted" in a.reason

    def test_trustee_disclosure_is_not_a_promoter_event(self):
        a = assess_disclosure(SEP22_TEXT, SEP22_CORRECT_EXTRACTION)
        assert not a.alert
        assert a.verified
        assert a.role == "non_promoter"

    def test_release_offset_by_ndu_is_not_a_release(self):
        # Even had a promoter filed it, pledge -> NDU on the same shares
        # leaves the encumbrance where it was.
        a = assess_disclosure(as_promoter(SEP22_TEXT), SEP22_CORRECT_EXTRACTION)
        assert not a.alert
        assert a.net_release_pct == 0
        assert a.action_type == "Unchanged"
        assert "moved +0.00 pp" in a.reason

    def test_figure_the_model_calculated_is_refused(self):
        # 26.31 + 6.22 = 32.53 is arithmetic, not something the filing prints.
        extraction = dict(SEP22_CORRECT_EXTRACTION,
                          encumbered_pct_before=32.53,
                          legs=[{"type": "Released", "pct": 6.22}])
        a = assess_disclosure(as_promoter(SEP22_TEXT), extraction)
        assert not a.alert
        assert "32.53% is not printed" in a.reason

    def test_legs_must_reconcile_with_before_and_after(self):
        # Dropping the NDU leg, as the old prompt did, no longer adds up.
        extraction = dict(SEP22_CORRECT_EXTRACTION,
                          legs=[{"type": "Released", "pct": 6.22}])
        a = assess_disclosure(as_promoter(SEP22_TEXT), extraction)
        assert not a.alert
        assert "legs sum to -6.22" in a.reason

    def test_genuine_promoter_release_alerts(self):
        a = assess_disclosure(REG31_RELEASE_TEXT, REG31_RELEASE_EXTRACTION)
        assert a.alert, a.reason
        assert a.net_release_pct == 10.0
        assert a.action_type == "Released"

    def test_invocation_is_never_a_release(self):
        extraction = dict(REG31_RELEASE_EXTRACTION,
                          legs=[{"type": "Invoked", "pct": 10.0}])
        a = assess_disclosure(REG31_RELEASE_TEXT, extraction)
        assert not a.alert
        assert a.action_type == "Invoked"

    def test_small_release_is_below_the_threshold(self):
        text = REG31_RELEASE_TEXT.replace("40.00", "31.00")
        extraction = dict(REG31_RELEASE_EXTRACTION, encumbered_pct_before=31.0,
                          legs=[{"type": "Released", "pct": 1.0}])
        a = assess_disclosure(text, extraction)
        assert not a.alert
        assert f"at least {MIN_NET_RELEASE_PCT:.1f} pp" in a.reason

    def test_unknown_discloser_fails_closed(self):
        text = "Encumbered before 40.00 after 30.00"
        a = assess_disclosure(text, REG31_RELEASE_EXTRACTION)
        assert not a.alert
        assert a.role == "unknown"

    def test_printed_check_does_not_match_inside_longer_numbers(self):
        # 6.2 is not printed; 6.22 and 26.31 are.
        extraction = dict(SEP22_CORRECT_EXTRACTION, encumbered_pct_before=6.2, legs=[])
        a = assess_disclosure(as_promoter(SEP22_TEXT), extraction)
        assert not a.alert
        assert "6.20% is not printed" in a.reason


# ── End to end, with Gemini, the graph and Telegram stubbed ─────────────


class StubEngine:
    def __init__(self, text, extraction):
        self.text, self.extraction = text, extraction

    def extract_text_from_pdf(self, pdf_path):
        return self.text

    def analyze_pledge_document(self, text):
        return dict(self.extraction)


class ConnectedGraph:
    """Every company is connected, as Patel Engineering was: a direct donor."""

    def alpha_query(self, cin):
        return [{"alpha_score": 1.22, "director_name": "DIRECT_DONOR",
                 "donor_company_name": "Patel Engineering Limited",
                 "is_bureaucrat": 0}]


class EmptyGraph:
    def alpha_query(self, cin):
        return []


class RecordingNotifier:
    def __init__(self):
        self.messages = []

    def _send_message(self, text, parse_mode="HTML"):
        self.messages.append(text)
        return True


def pledge_event(scrip_code, attachment=SEP22_ATTACHMENT):
    return SimpleNamespace(
        scrip_code=scrip_code, date="2026-09-22",
        title="Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011",
        raw_data={"pdf_path": "filing.pdf", "ATTACHMENTNAME": attachment},
    )


@pytest.fixture
def monitor(cache):
    cache.upsert_company(scrip_code="531120", name="Patel Engineering Limited",
                         cin="L99999MH1949PLC007039")
    cache.upsert_company(scrip_code="500001", name="Example & Sons Infra Ltd",
                         cin="L45200MH2000PLC000001")

    def build(text, extraction, graph=None):
        notifier = RecordingNotifier()
        m = PledgeMonitor(cache, notifier, graph or ConnectedGraph(),
                          StubEngine(text, extraction))
        return m, notifier

    return build


def pledge_rows(cache, scrip_code):
    with cache._connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT action_type, total_pledged_pct FROM pledges WHERE scrip_code = ?",
            (scrip_code,))]


class TestPledgeMonitor:
    @pytest.mark.parametrize("extraction", [SEP22_OLD_EXTRACTION, SEP22_CORRECT_EXTRACTION],
                             ids=["old-prompt-output", "correct-reading"])
    def test_sep22_filing_sends_nothing(self, monitor, extraction):
        m, notifier = monitor(SEP22_TEXT, extraction)
        assert m.process_pledge_events([pledge_event("531120")]) == 0
        assert notifier.messages == []

    def test_non_promoter_figures_never_reach_the_pledge_table(self, monitor, cache):
        # alpha_engine blocks contract alerts when the latest total_pledged_pct
        # is 25% or more, so a trustee's 26.31% must not be stored as a
        # promoter pledge level.
        m, _ = monitor(SEP22_TEXT, SEP22_CORRECT_EXTRACTION)
        m.process_pledge_events([pledge_event("531120")])
        assert pledge_rows(cache, "531120") == []

    def test_genuine_release_sends_one_factual_alert(self, monitor, cache):
        m, notifier = monitor(REG31_RELEASE_TEXT, REG31_RELEASE_EXTRACTION)
        assert m.process_pledge_events([pledge_event("500001", "abc.pdf")]) == 1

        [msg] = notifier.messages
        assert "40.00% → 30.00%" in msg
        assert "net release 10.00 pp" in msg
        assert "bseindia.com/xml-data/corpfiling/AttachLive/abc.pdf" in msg
        assert "Untested" in msg
        assert "front-running" not in msg.lower()
        assert "insider" not in msg.lower()
        assert pledge_rows(cache, "500001") == [
            {"action_type": "Released", "total_pledged_pct": 30.0}]

    def test_names_are_escaped_for_telegram_html(self, monitor):
        # An unescaped "&" makes Telegram reject the whole message.
        m, notifier = monitor(REG31_RELEASE_TEXT, REG31_RELEASE_EXTRACTION)
        m.process_pledge_events([pledge_event("500001")])
        assert "Example &amp; Sons Infra Ltd" in notifier.messages[0]

    def test_same_disclosure_alerts_only_once(self, monitor):
        m, notifier = monitor(REG31_RELEASE_TEXT, REG31_RELEASE_EXTRACTION)
        assert m.process_pledge_events([pledge_event("500001")]) == 1
        assert m.process_pledge_events([pledge_event("500001")]) == 0
        assert len(notifier.messages) == 1

    def test_unconnected_company_is_recorded_but_not_alerted(self, monitor, cache):
        m, notifier = monitor(REG31_RELEASE_TEXT, REG31_RELEASE_EXTRACTION,
                              graph=EmptyGraph())
        assert m.process_pledge_events([pledge_event("500001")]) == 0
        assert notifier.messages == []
        assert len(pledge_rows(cache, "500001")) == 1
