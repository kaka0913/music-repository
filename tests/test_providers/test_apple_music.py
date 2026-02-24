from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import Track
from src.providers.apple_music import AppleMusicProvider
from src.providers.base import AuthenticationError


FAKE_SELECTORS = {
    "logged_in_indicator": ".logged-in",
    "playlist_track_row": ".track-row",
    "track_title": ".track-title",
    "track_artist": ".track-artist",
    "search_input": "input[type=search]",
    "search_result_row": ".search-result-row",
    "add_to_playlist_button": ".add-to-playlist",
}


def _make_mock_browser_context(page: AsyncMock) -> MagicMock:
    """browser_context のモックを生成するヘルパー。"""
    ctx = AsyncMock()

    @asynccontextmanager
    async def _fake_browser_context(**kwargs):
        yield ctx, page

    return _fake_browser_context


@pytest.fixture
def provider() -> AppleMusicProvider:
    """Cookie とセレクタを設定済みの AppleMusicProvider を返すフィクスチャ。"""
    p = AppleMusicProvider()
    p._cookies = [{"name": "session", "value": "abc", "domain": ".apple.com", "path": "/"}]
    p._selectors = FAKE_SELECTORS
    return p


class TestAuthenticate:
    """authenticate() メソッドのテスト。"""

    @patch("src.providers.apple_music.get_selectors")
    @patch("src.providers.apple_music.load_cookies_from_secret")
    def test_authenticate_success(
        self, mock_load_cookies: MagicMock, mock_get_selectors: MagicMock
    ) -> None:
        """load_cookies_from_secret と get_selectors をモックして認証成功を確認。"""
        mock_load_cookies.return_value = [
            {"name": "session", "value": "abc", "domain": ".apple.com", "path": "/"}
        ]
        mock_get_selectors.return_value = FAKE_SELECTORS

        provider = AppleMusicProvider()
        provider.authenticate()

        mock_load_cookies.assert_called_once_with("apple-music-cookie")
        mock_get_selectors.assert_called_once_with("apple_music")
        assert len(provider._cookies) == 1
        assert provider._selectors == FAKE_SELECTORS

    @patch("src.providers.apple_music.load_cookies_from_secret")
    def test_authenticate_failure(self, mock_load_cookies: MagicMock) -> None:
        """load_cookies_from_secret が例外を投げた場合に AuthenticationError が発生することを確認。"""
        mock_load_cookies.side_effect = Exception("Secret not found")

        provider = AppleMusicProvider()

        with pytest.raises(AuthenticationError, match="Apple Music authentication failed"):
            provider.authenticate()


class TestGetPlaylistTracks:
    """get_playlist_tracks() メソッドのテスト。"""

    @patch("src.providers.apple_music.browser_context")
    def test_get_playlist_tracks(
        self, mock_browser_ctx: MagicMock, provider: AppleMusicProvider
    ) -> None:
        """browser_context をモックして Track リストが返されることを確認。"""
        page = AsyncMock()

        # ログイン状態の確認 -> ログイン済み
        page.query_selector.return_value = AsyncMock()

        # トラック行のモック
        row1 = AsyncMock()
        title_el1 = AsyncMock()
        title_el1.inner_text = AsyncMock(return_value="Bohemian Rhapsody")
        artist_el1 = AsyncMock()
        artist_el1.inner_text = AsyncMock(return_value="Queen")

        async def row1_query_selector(selector: str):
            if selector == FAKE_SELECTORS["track_title"]:
                return title_el1
            if selector == FAKE_SELECTORS["track_artist"]:
                return artist_el1
            return None

        row1.query_selector = AsyncMock(side_effect=row1_query_selector)

        row2 = AsyncMock()
        title_el2 = AsyncMock()
        title_el2.inner_text = AsyncMock(return_value="Imagine")
        artist_el2 = AsyncMock()
        artist_el2.inner_text = AsyncMock(return_value="John Lennon")

        async def row2_query_selector(selector: str):
            if selector == FAKE_SELECTORS["track_title"]:
                return title_el2
            if selector == FAKE_SELECTORS["track_artist"]:
                return artist_el2
            return None

        row2.query_selector = AsyncMock(side_effect=row2_query_selector)

        page.query_selector_all = AsyncMock(return_value=[row1, row2])

        mock_browser_ctx.return_value = _make_mock_browser_context(page)()

        playlist_url = "https://music.apple.com/jp/playlist/my-playlist/pl.12345"
        tracks = provider.get_playlist_tracks(playlist_url)

        assert len(tracks) == 2

        assert tracks[0].title == "Bohemian Rhapsody"
        assert tracks[0].artist == "Queen"
        assert tracks[0].isrc is None
        assert tracks[0].album == ""
        assert tracks[0].service_ids == {"apple_music": playlist_url}

        assert tracks[1].title == "Imagine"
        assert tracks[1].artist == "John Lennon"
        assert tracks[1].isrc is None
        assert tracks[1].service_ids == {"apple_music": playlist_url}


class TestSearchTrack:
    """search_track() メソッドのテスト。"""

    @patch("src.providers.apple_music.browser_context")
    def test_search_track_found(
        self, mock_browser_ctx: MagicMock, provider: AppleMusicProvider
    ) -> None:
        """browser_context をモックして Track が返されることを確認。"""
        page = AsyncMock()

        # search_input のモック
        search_input = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=search_input)

        # 検索結果行のモック
        result_row = AsyncMock()

        title_el = AsyncMock()
        title_el.inner_text = AsyncMock(return_value="Bohemian Rhapsody")
        artist_el = AsyncMock()
        artist_el.inner_text = AsyncMock(return_value="Queen")

        async def result_query_selector(selector: str):
            if selector == FAKE_SELECTORS["track_title"]:
                return title_el
            if selector == FAKE_SELECTORS["track_artist"]:
                return artist_el
            return None

        result_row.query_selector = AsyncMock(side_effect=result_query_selector)

        page.query_selector = AsyncMock(return_value=result_row)

        mock_browser_ctx.return_value = _make_mock_browser_context(page)()

        result = provider.search_track("Bohemian Rhapsody", "Queen")

        assert result is not None
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.isrc is None
        assert result.album == ""
        assert result.service_ids == {"apple_music": None}

        search_input.fill.assert_called_once_with("Bohemian Rhapsody Queen")
        search_input.press.assert_called_once_with("Enter")

    @patch("src.providers.apple_music.browser_context")
    def test_search_track_not_found(
        self, mock_browser_ctx: MagicMock, provider: AppleMusicProvider
    ) -> None:
        """検索結果なしで None が返ることを確認。"""
        page = AsyncMock()

        search_input = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=search_input)

        # 検索結果なし
        page.query_selector = AsyncMock(return_value=None)

        mock_browser_ctx.return_value = _make_mock_browser_context(page)()

        result = provider.search_track("Nonexistent Song", "Unknown Artist")

        assert result is None
