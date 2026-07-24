"""
Political Alpha Tracker — Telegram Notifier

Sends formatted alerts to a private Telegram bot and manages
the held_positions lifecycle:
    - Adds companies to held_positions when alerts fire
    - Polls for /exit commands to remove positions
    - Sends system health alerts

Also handles auto-expiry of held positions.
"""

import logging
from datetime import datetime
from typing import Optional

import requests

from src.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_API_BASE,
    HELD_POSITION_EXPIRY_DAYS,
)
from src.cache_manager import CacheManager
from src.financial_screener import FundamentalResult

logger = logging.getLogger(__name__)


class Notifier:
    """
    Sends Telegram alerts and manages held positions.

    Usage:
        notifier = Notifier(cache)
        notifier.send_alpha_alert(connection, fundamental, announcement)
        notifier.poll_exit_commands()
    """

    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.api_base = TELEGRAM_API_BASE.format(token=TELEGRAM_BOT_TOKEN)
        self.enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

        if not self.enabled:
            logger.warning(
                "Telegram not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )

    def _send_message(self, text: str,
                       parse_mode: str = "HTML") -> bool:
        """
        Send a message to the configured Telegram chat.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.enabled:
            logger.info(f"[DRY RUN] Telegram message:\n{text}")
            return False

        try:
            resp = requests.post(
                f"{self.api_base}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            resp.raise_for_status()

            result = resp.json()
            if result.get("ok"):
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(
                    f"Telegram API error: {result.get('description')}"
                )
                return False

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_alpha_alert(self, connection: dict,
                          fundamental: FundamentalResult = None,
                          announcement: dict = None):
        """
        Send a political alpha alert to Telegram.

        Args:
            connection: Dict from GraphManager.alpha_query() result
            fundamental: FundamentalResult for the company
            announcement: The triggering BSE announcement dict
        """
        score = connection.get("alpha_score", 0)
        company = connection.get("company_name", "Unknown")
        scrip = connection.get("scrip_code", "")
        director = connection.get("director_name", "Unknown")
        din = connection.get("director_din", "")
        donor = connection.get("donor_company_name", "Unknown")
        trust = connection.get("trust_name", "")
        donation = connection.get("max_donation", 0)
        donation_year = connection.get("donation_year", "")
        board_seats = connection.get("total_board_seats", 0)

        # Format donation amount
        if donation >= 1e7:
            donation_str = f"₹{donation / 1e7:.1f} Cr"
        elif donation >= 1e5:
            donation_str = f"₹{donation / 1e5:.1f} Lakh"
        else:
            donation_str = f"₹{donation:,.0f}"

        # Build the alert message
        lines = [
            "🚨 <b>POLITICAL ALPHA ALERT</b>",
            "",
            f"📊 <b>Company:</b> {company} (BSE: {scrip})",
        ]

        if announcement:
            lines.append(
                f"📋 <b>Contract:</b> {announcement.get('title', 'N/A')}"
            )
            lines.append(
                f"📅 <b>Date:</b> {announcement.get('date', 'N/A')}"
            )

        lines.extend([
            "",
            f"🔗 <b>Political Connection (Score: {score:.2f}):</b>",
            f"   Director: {director} (DIN: {din})",
            f"   Also on board of: {donor}",
            f"   Which donated: {donation_str} → {trust}",
            f"   Board seats: {board_seats} (fewer = stronger signal)",
        ])

        if fundamental:
            lines.extend([
                "",
                f"📈 <b>Fundamentals:</b> {fundamental.summary()}",
            ])

        lines.extend([
            "",
            "⏳ <b>Strategy:</b> Wait for drift to 50-DMA before entry.",
            f"💡 Reply <code>/exit {scrip}</code> when you close the trade.",
        ])

        text = "\n".join(lines)
        self._send_message(text)

        # Auto-add to held positions
        self.cache.add_held_position(
            scrip_code=scrip,
            name=company,
            alpha_score=score,
            expiry_days=HELD_POSITION_EXPIRY_DAYS,
        )

        self.cache.log_event(
            "notifier", "alpha_alert_sent",
            f"Alert for {company} ({scrip}), score: {score:.2f}"
        )

    def send_system_alert(self, title: str, details: str,
                           level: str = "INFO"):
        """
        Send a system health/status alert.

        Args:
            title: Alert title
            details: Alert details
            level: Severity level (INFO, WARNING, ERROR)
        """
        emoji_map = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "🔴",
        }
        emoji = emoji_map.get(level, "ℹ️")

        text = (
            f"{emoji} <b>{title}</b>\n\n"
            f"{details}\n\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M IST')}"
        )

        self._send_message(text)

    def send_daily_summary(self, contracts_found: int,
                            alerts_fired: int,
                            watchlist_size: int,
                            graph_stats: dict = None):
        """Send end-of-day pipeline summary."""
        lines = [
            "📊 <b>Daily Pipeline Summary</b>",
            "",
            f"📋 Watchlist size: {watchlist_size}",
            f"🔍 Contracts found: {contracts_found}",
            f"🚨 Alerts fired: {alerts_fired}",
        ]

        if graph_stats:
            lines.extend([
                "",
                f"🔗 Graph: {graph_stats.get('total_nodes', 0)} nodes, "
                f"{graph_stats.get('total_edges', 0)} edges",
            ])

        held = self.cache.get_held_positions()
        if held:
            lines.append(f"📌 Active positions: {len(held)}")

        lines.append(
            f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M IST')}"
        )

        self._send_message("\n".join(lines))

    def poll_exit_commands(self) -> list[str]:
        """
        Poll Telegram for /exit commands to remove held positions.
        Called at the start of each daily pipeline run.

        Returns:
            List of scrip codes that were removed.
        """
        if not self.enabled:
            return []

        removed = []

        try:
            resp = requests.get(
                f"{self.api_base}/getUpdates",
                params={"timeout": 5, "allowed_updates": '["message"]'},
                timeout=15,
            )
            resp.raise_for_status()

            data = resp.json()
            if not data.get("ok"):
                return []

            updates = data.get("result", [])
            max_update_id = None

            for update in updates:
                max_update_id = update.get("update_id", max_update_id)
                message = update.get("message", {})
                text = message.get("text", "").strip()
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Only process messages from our configured chat
                if chat_id != TELEGRAM_CHAT_ID:
                    continue

                # Check for /exit command
                if text.lower().startswith("/exit"):
                    parts = text.split()
                    if len(parts) >= 2:
                        scrip_code = parts[1].strip()
                        self.cache.remove_held_position(scrip_code)
                        removed.append(scrip_code)

                        self._send_message(
                            f"✅ Removed <b>{scrip_code}</b> from held positions."
                        )
                        logger.info(
                            f"Removed {scrip_code} from held positions "
                            f"via /exit command"
                        )

            # Mark updates as read
            if max_update_id is not None:
                requests.get(
                    f"{self.api_base}/getUpdates",
                    params={"offset": max_update_id + 1, "timeout": 1},
                    timeout=10,
                )

        except Exception as e:
            logger.warning(f"Failed to poll Telegram updates: {e}")

        # Also cleanup expired positions
        expired_count = self.cache.cleanup_expired_positions()
        if expired_count > 0:
            logger.info(f"Auto-expired {expired_count} held positions")

        return removed
