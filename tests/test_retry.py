from __future__ import annotations

from unittest.mock import patch

import pytest

from src.utils.retry import (
    NetworkError,
    RateLimitError,
    RetryableError,
    retry_with_backoff,
)


class TestRetryWithBackoff:
    """retry_with_backoff デコレータのテスト。"""

    @patch("src.utils.retry.time.sleep", return_value=None)
    def test_retry_success_on_first_try(self, mock_sleep):
        """リトライ不要で成功する場合、関数は1回だけ呼ばれる。"""
        call_count = 0

        @retry_with_backoff(max_retries=3)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed()

        assert result == "ok"
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.utils.retry.time.sleep", return_value=None)
    def test_retry_success_after_failure(self, mock_sleep):
        """1回失敗後に成功する場合、関数は2回呼ばれる。"""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError("rate limited")
            return "ok"

        result = fail_then_succeed()

        assert result == "ok"
        assert call_count == 2
        # 1回目の失敗後に sleep が1回呼ばれる (delay = 1.0 * 2^0 = 1.0)
        mock_sleep.assert_called_once_with(1.0)

    @patch("src.utils.retry.time.sleep", return_value=None)
    def test_retry_all_failures(self, mock_sleep):
        """全リトライ失敗で例外が raise される。"""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise NetworkError("network error")

        with pytest.raises(NetworkError, match="network error"):
            always_fail()

        # 初回 + 3回リトライ = 4回呼ばれる
        assert call_count == 4
        # sleep は3回呼ばれる (リトライの間)
        assert mock_sleep.call_count == 3

    @patch("src.utils.retry.time.sleep", return_value=None)
    def test_retry_non_retryable_error(self, mock_sleep):
        """RetryableError 以外は即座に raise される。"""
        call_count = 0

        @retry_with_backoff(max_retries=3)
        def raise_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("non-retryable")

        with pytest.raises(ValueError, match="non-retryable"):
            raise_value_error()

        # リトライせず1回だけ呼ばれる
        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.utils.retry.time.sleep", return_value=None)
    def test_retry_backoff_delays(self, mock_sleep):
        """指数バックオフのディレイが正しく計算される。"""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=2.0, max_delay=60.0)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise RetryableError("error")

        with pytest.raises(RetryableError):
            always_fail()

        # 期待されるディレイ: 2.0, 4.0, 8.0
        assert mock_sleep.call_args_list[0][0][0] == 2.0
        assert mock_sleep.call_args_list[1][0][0] == 4.0
        assert mock_sleep.call_args_list[2][0][0] == 8.0

    @patch("src.utils.retry.time.sleep", return_value=None)
    def test_retry_max_delay_cap(self, mock_sleep):
        """max_delay でディレイが上限に制限される。"""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=10.0, max_delay=15.0)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise RetryableError("error")

        with pytest.raises(RetryableError):
            always_fail()

        # 期待されるディレイ: 10.0, 15.0 (20.0 -> capped), 15.0 (40.0 -> capped)
        assert mock_sleep.call_args_list[0][0][0] == 10.0
        assert mock_sleep.call_args_list[1][0][0] == 15.0
        assert mock_sleep.call_args_list[2][0][0] == 15.0
