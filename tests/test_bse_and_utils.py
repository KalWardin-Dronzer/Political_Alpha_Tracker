"""
Tests for BSEMonitor — announcement classification and scanning.

Tests classification logic offline (no network calls).
"""

import pytest

from src.bse_monitor import BSEMonitor


class TestAnnouncementClassification:
    """Tests for the regex-based announcement classifier."""

    @pytest.fixture
    def monitor(self, cache):
        return BSEMonitor(cache)

    # ── Contract Detection ──

    @pytest.mark.parametrize("title", [
        "Award of Order worth ₹450 Cr from Indian Railways",
        "Company has received order from PGCIL",
        "Order Received for supply of smart meters",
        "Tender Award - EPC contract for solar plant",
        "Letter of Acceptance received from NHAI",
        "LOA received for highway project",
        "Contract Award from Ministry of Defence",
        "New Work Order from Metro Rail Corporation",
        "EPC Contract for 132 KV substation",
        "Supply Order from State Electricity Board",
        "Company has bagged order worth Rs 200 Cr",
        "Company secured new order from Railways",
    ])
    def test_detects_contract_announcements(self, monitor, title):
        result = monitor._classify_announcement(title)
        assert result == "contract", f"Failed to classify as contract: {title}"

    # ── Board Change Detection ──

    @pytest.mark.parametrize("title", [
        "Appointment of Mr. X as Independent Director",
        "Resignation of Director Mr. Y",
        "Cessation of Mr. Z as Director",
        "Change in Board Composition",
        "Appointment of Key Managerial Personnel",
        "Change in Directors",
    ])
    def test_detects_board_changes(self, monitor, title):
        result = monitor._classify_announcement(title)
        assert result == "board_change", f"Failed to classify as board_change: {title}"

    # ── False Positive Exclusions ──

    @pytest.mark.parametrize("title", [
        "Order of NCLT regarding merger",
        "NCLAT Order on insolvency proceedings",
        "SEBI Order - Adjudication penalty",
        "Court Order regarding dispute",
        "Regulatory Order from CERC",
    ])
    def test_excludes_regulatory_orders(self, monitor, title):
        result = monitor._classify_announcement(title)
        assert result is None, f"Should NOT classify as contract: {title}"

    # ── Irrelevant Announcements ──

    @pytest.mark.parametrize("title", [
        "Outcome of Board Meeting",
        "Financial Results for Q1 FY2026",
        "Record Date for Dividend",
        "Annual General Meeting Notice",
        "Investor Presentation",
        "Credit Rating Update",
    ])
    def test_ignores_irrelevant_announcements(self, monitor, title):
        result = monitor._classify_announcement(title)
        assert result is None, f"Should be None for irrelevant: {title}"


class TestDonorAmountParsing:
    """Tests for Indian amount format parsing used by donor_ingester."""

    def test_crore_format(self):
        from src.donor_ingester import parse_amount
        assert parse_amount("5.2 Crore") == 52_000_000
        assert parse_amount("52.5 Cr") == 525_000_000
        assert parse_amount("1 crore") == 10_000_000

    def test_lakh_format(self):
        from src.donor_ingester import parse_amount
        assert parse_amount("10 Lakh") == 1_000_000
        assert parse_amount("50 lakhs") == 5_000_000

    def test_raw_number_format(self):
        from src.donor_ingester import parse_amount
        assert parse_amount("5,00,00,000") == 50_000_000
        assert parse_amount("10,00,000") == 1_000_000

    def test_rupee_symbol(self):
        from src.donor_ingester import parse_amount
        result = parse_amount("₹ 10,00,000")
        assert result == 1_000_000

    def test_empty_and_none(self):
        from src.donor_ingester import parse_amount
        assert parse_amount("") is None
        assert parse_amount(None) is None


class TestFinancialResult:
    """Tests for the FundamentalResult dataclass."""

    def test_summary_format(self):
        from src.financial_screener import FundamentalResult
        result = FundamentalResult(
            scrip_code="540001",
            company_name="Test Co",
            passes=True,
            de_ratio=0.8,
            operating_cashflow=120_000_000,
            promoter_pledge_pct=0.0,
        )
        summary = result.summary()
        assert "PASS" in summary
        assert "0.8" in summary

    def test_summary_failure(self):
        from src.financial_screener import FundamentalResult
        result = FundamentalResult(
            scrip_code="540001",
            company_name="Bad Co",
            passes=False,
            de_ratio=3.5,
        )
        summary = result.summary()
        assert "FAIL" in summary

    def test_summary_unavailable(self):
        from src.financial_screener import FundamentalResult
        result = FundamentalResult(
            scrip_code="540001",
            company_name="Unknown Co",
            passes=False,
            data_available=False,
        )
        summary = result.summary()
        assert "unavailable" in summary.lower()


class TestNotifierFormatting:
    """Tests for Telegram message formatting (offline, no API calls)."""

    def test_notifier_disabled_without_token(self, cache):
        from src.notifier import Notifier
        notifier = Notifier(cache)
        assert notifier.enabled is False

    def test_send_message_dry_run(self, cache):
        from src.notifier import Notifier
        notifier = Notifier(cache)
        result = notifier._send_message("Test message")
        assert result is False  # No token configured
