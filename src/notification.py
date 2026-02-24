from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from src.models import SyncResult

logger = logging.getLogger(__name__)


def build_error_message(results: dict[str, SyncResult]) -> str | None:
    """同期結果からエラーメッセージ本文を組み立てる。エラーや未同期がなければ None を返す。"""
    lines: list[str] = []

    # エラー集約
    error_lines: list[str] = []
    for playlist_name, result in results.items():
        for error in result.errors:
            error_lines.append(f"  - [{playlist_name}] {error}")

    if error_lines:
        lines.append("■ エラー")
        lines.extend(error_lines)
        lines.append("")

    # 未同期楽曲集約
    unmatched_lines: list[str] = []
    for playlist_name, result in results.items():
        for item in result.unmatched:
            title = item.get("title", "Unknown")
            artist = item.get("artist", "Unknown")
            reason = item.get("reason", "")
            unmatched_lines.append(f'  - "{title}" by {artist} → {reason}')

    if unmatched_lines:
        lines.append(f"■ 未同期楽曲 ({len(unmatched_lines)}曲)")
        lines.extend(unmatched_lines)
        lines.append("")

    if not lines:
        return None

    return "\n".join(lines)


def send_notification(
    to_email: str,
    subject: str,
    body: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
    gmail_app_password: str = "",
    from_email: str = "",
) -> None:
    """Gmail SMTP 経由でメールを送信する。"""
    if not from_email:
        from_email = to_email

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(from_email, gmail_app_password)
            server.send_message(msg)
        logger.info("Notification email sent to %s", to_email)
    except Exception:
        logger.exception("Failed to send notification email")
        raise


def notify_if_needed(
    results: dict[str, SyncResult],
    to_email: str,
    gmail_app_password: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> bool:
    """エラーや未同期楽曲がある場合のみ通知メールを送信。送信した場合 True を返す。"""
    body = build_error_message(results)
    if body is None:
        logger.info("No errors or unmatched tracks. Skipping notification.")
        return False

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[Music Sync] エラー検知 - {now}"

    send_notification(
        to_email=to_email,
        subject=subject,
        body=body,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        gmail_app_password=gmail_app_password,
    )
    return True
