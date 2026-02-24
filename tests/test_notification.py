from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.models import SyncResult
from src.notification import build_error_message, notify_if_needed, send_notification


class TestBuildErrorMessage:
    def test_build_error_message_with_errors(self) -> None:
        """エラーがある SyncResult を渡して、メッセージに '■ エラー' が含まれることを確認。"""
        results = {
            "My Playlist": SyncResult(
                errors=["API rate limit exceeded", "Timeout error"],
            ),
        }
        message = build_error_message(results)
        assert message is not None
        assert "■ エラー" in message
        assert "[My Playlist] API rate limit exceeded" in message
        assert "[My Playlist] Timeout error" in message

    def test_build_error_message_with_unmatched(self) -> None:
        """unmatched がある SyncResult を渡して、メッセージに '■ 未同期楽曲' が含まれることを確認。"""
        results = {
            "Rock Hits": SyncResult(
                unmatched=[
                    {"title": "Some Song", "artist": "Some Artist", "reason": "Not found"},
                    {"title": "Another", "artist": "Band", "reason": "Region locked"},
                ],
            ),
        }
        message = build_error_message(results)
        assert message is not None
        assert "■ 未同期楽曲" in message
        assert "(2曲)" in message
        assert '"Some Song" by Some Artist' in message
        assert '"Another" by Band' in message

    def test_build_error_message_no_issues(self) -> None:
        """エラーも unmatched もない SyncResult を渡して None が返ることを確認。"""
        results = {
            "Clean Playlist": SyncResult(),
        }
        message = build_error_message(results)
        assert message is None


class TestSendNotification:
    def test_send_notification(self) -> None:
        """smtplib.SMTP をモックして、starttls, login, send_message が呼ばれることを確認。"""
        with patch("src.notification.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_notification(
                to_email="user@example.com",
                subject="Test Subject",
                body="Test body",
                smtp_host="smtp.gmail.com",
                smtp_port=587,
                gmail_app_password="app-password",
                from_email="sender@example.com",
            )

            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("sender@example.com", "app-password")
            mock_server.send_message.assert_called_once()


class TestNotifyIfNeeded:
    def test_notify_if_needed_sends(self) -> None:
        """エラーがある場合に send_notification が呼ばれて True が返ることを確認。"""
        results = {
            "Playlist A": SyncResult(errors=["Something went wrong"]),
        }
        with patch("src.notification.send_notification") as mock_send:
            sent = notify_if_needed(
                results=results,
                to_email="user@example.com",
                gmail_app_password="app-password",
            )
            assert sent is True
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs["to_email"] == "user@example.com"
            assert "[Music Sync]" in call_kwargs["subject"]

    def test_notify_if_needed_skips(self) -> None:
        """問題ない場合に False が返ることを確認。"""
        results = {
            "Playlist B": SyncResult(),
        }
        with patch("src.notification.send_notification") as mock_send:
            sent = notify_if_needed(
                results=results,
                to_email="user@example.com",
                gmail_app_password="app-password",
            )
            assert sent is False
            mock_send.assert_not_called()
