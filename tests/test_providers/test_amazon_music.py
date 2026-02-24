from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import Track
from src.providers.base import AuthenticationError
from src.providers.amazon_music import AmazonMusicProvider, _extract_isrc_map_from_api_response


FAKE_COOKIES = [{"name": "session-id", "value": "abc123", "domain": ".amazon.co.jp", "path": "/"}]

FAKE_SELECTORS = {
    "logged_in_indicator": "#nav-link-accountList",
    "playlist_track_row": "music-track-row",
    "track_title": ".title-text",
    "track_artist": ".artist-text",
    "search_input": "#searchInput",
    "search_result_row": ".search-result-row",
    "add_to_playlist_button": ".add-to-playlist-btn",
}


@pytest.fixture
def provider() -> AmazonMusicProvider:
    """Cookie・セレクタ設定済みの AmazonMusicProvider を返すフィクスチャ。"""
    p = AmazonMusicProvider()
    p._cookies = FAKE_COOKIES
    p._selectors = FAKE_SELECTORS
    return p


def _make_mock_browser_context(page: AsyncMock):
    """browser_context をモックする async context manager を生成する。"""

    @asynccontextmanager
    async def _mock_browser_context(**kwargs):
        ctx = AsyncMock()
        yield ctx, page

    return _mock_browser_context


class TestAuthenticate:
    """authenticate() メソッドのテスト。"""

    @patch("src.providers.amazon_music.get_selectors")
    @patch("src.providers.amazon_music.load_cookies_from_secret")
    def test_authenticate_success(
        self, mock_load_cookies: MagicMock, mock_get_selectors: MagicMock
    ) -> None:
        """load_cookies_from_secret と get_selectors をモックして認証成功を確認。"""
        mock_load_cookies.return_value = FAKE_COOKIES
        mock_get_selectors.return_value = FAKE_SELECTORS

        provider = AmazonMusicProvider()
        provider.authenticate()

        mock_load_cookies.assert_called_once_with("amazon-music-cookie")
        mock_get_selectors.assert_called_once_with("amazon_music")
        assert provider._cookies == FAKE_COOKIES
        assert provider._selectors == FAKE_SELECTORS

    @patch("src.providers.amazon_music.load_cookies_from_secret")
    def test_authenticate_failure(self, mock_load_cookies: MagicMock) -> None:
        """load_cookies_from_secret が例外を投げた場合に AuthenticationError が発生することを確認。"""
        mock_load_cookies.side_effect = Exception("Secret not found")

        provider = AmazonMusicProvider()

        with pytest.raises(AuthenticationError, match="Amazon Music authentication failed"):
            provider.authenticate()


class TestGetPlaylistTracks:
    """get_playlist_tracks() メソッドのテスト。"""

    @patch("src.providers.amazon_music.browser_context")
    def test_get_playlist_tracks(self, mock_bc: MagicMock, provider: AmazonMusicProvider) -> None:
        """browser_context をモックして Track リストが返されることを確認。"""
        mock_page = AsyncMock()

        # logged_in_indicator が見つかる（ログイン済み）
        mock_page.query_selector.return_value = AsyncMock()

        # 2行分のトラック行をモック
        row1 = AsyncMock()
        title_el1 = AsyncMock()
        title_el1.inner_text = AsyncMock(return_value="Bohemian Rhapsody")
        artist_el1 = AsyncMock()
        artist_el1.inner_text = AsyncMock(return_value="Queen")
        row1.query_selector = AsyncMock(side_effect=lambda sel: {
            FAKE_SELECTORS["track_title"]: title_el1,
            FAKE_SELECTORS["track_artist"]: artist_el1,
        }.get(sel))

        row2 = AsyncMock()
        title_el2 = AsyncMock()
        title_el2.inner_text = AsyncMock(return_value="Imagine")
        artist_el2 = AsyncMock()
        artist_el2.inner_text = AsyncMock(return_value="John Lennon")
        row2.query_selector = AsyncMock(side_effect=lambda sel: {
            FAKE_SELECTORS["track_title"]: title_el2,
            FAKE_SELECTORS["track_artist"]: artist_el2,
        }.get(sel))

        mock_page.query_selector_all = AsyncMock(return_value=[row1, row2])

        mock_bc.return_value = _make_mock_browser_context(mock_page)()

        playlist_url = "https://music.amazon.co.jp/playlists/B0EXAMPLE"
        tracks = provider.get_playlist_tracks(playlist_url)

        assert len(tracks) == 2

        assert tracks[0].title == "Bohemian Rhapsody"
        assert tracks[0].artist == "Queen"
        assert tracks[0].album == ""
        assert tracks[0].isrc is None
        assert tracks[0].service_ids == {"amazon_music": playlist_url}

        assert tracks[1].title == "Imagine"
        assert tracks[1].artist == "John Lennon"
        assert tracks[1].album == ""
        assert tracks[1].isrc is None
        assert tracks[1].service_ids == {"amazon_music": playlist_url}


class TestSearchTrack:
    """search_track() メソッドのテスト。"""

    @patch("src.providers.amazon_music.browser_context")
    def test_search_track_found(self, mock_bc: MagicMock, provider: AmazonMusicProvider) -> None:
        """browser_context をモックして Track が返されることを確認。"""
        mock_page = AsyncMock()

        # search_input
        mock_search_input = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(return_value=mock_search_input)

        # search result row
        result_row = AsyncMock()
        title_el = AsyncMock()
        title_el.inner_text = AsyncMock(return_value="Bohemian Rhapsody")
        artist_el = AsyncMock()
        artist_el.inner_text = AsyncMock(return_value="Queen")
        result_row.query_selector = AsyncMock(side_effect=lambda sel: {
            FAKE_SELECTORS["track_title"]: title_el,
            FAKE_SELECTORS["track_artist"]: artist_el,
        }.get(sel))

        mock_page.query_selector = AsyncMock(return_value=result_row)

        mock_bc.return_value = _make_mock_browser_context(mock_page)()

        result = provider.search_track("Bohemian Rhapsody", "Queen")

        assert result is not None
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.album == ""
        assert result.isrc is None
        assert result.service_ids == {"amazon_music": None}

    @patch("src.providers.amazon_music.browser_context")
    def test_search_track_not_found(self, mock_bc: MagicMock, provider: AmazonMusicProvider) -> None:
        """検索結果なしで None が返ることを確認。"""
        mock_page = AsyncMock()

        # search_input
        mock_search_input = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(return_value=mock_search_input)

        # 検索結果なし
        mock_page.query_selector = AsyncMock(return_value=None)

        mock_bc.return_value = _make_mock_browser_context(mock_page)()

        result = provider.search_track("Nonexistent Song", "Unknown Artist")

        assert result is None


class TestExtractIsrcMap:
    """_extract_isrc_map_from_api_response() のテスト。"""

    def test_nested_metadata(self) -> None:
        """metadata ネスト構造から ISRC/ASIN を抽出。"""
        api_response = {
            "methods": [
                {
                    "template": {
                        "widgets": [
                            {
                                "items": [
                                    {
                                        "title": "Bohemian Rhapsody",
                                        "isrc": "GBUM71029604",
                                        "asin": "B01N5XY2WQ",
                                    },
                                    {
                                        "title": "Imagine",
                                        "isrc": "USRC17000592",
                                        "asin": "B00137QLTY",
                                    },
                                ]
                            }
                        ]
                    }
                }
            ]
        }
        result = _extract_isrc_map_from_api_response(api_response)
        assert result == {
            "bohemian rhapsody": {"isrc": "GBUM71029604", "asin": "B01N5XY2WQ"},
            "imagine": {"isrc": "USRC17000592", "asin": "B00137QLTY"},
        }

    def test_metadata_with_catalogid(self) -> None:
        """catalogId を ASIN として抽出。"""
        api_response = {
            "tracks": [
                {
                    "metadata": {
                        "title": "Yesterday",
                        "isrc": "GBAYE0601477",
                    },
                    "catalogId": "B001234567",
                }
            ]
        }
        result = _extract_isrc_map_from_api_response(api_response)
        assert result["yesterday"]["isrc"] == "GBAYE0601477"
        assert result["yesterday"]["asin"] == "B001234567"

    def test_asin_only(self) -> None:
        """ISRC がなく ASIN のみの場合も抽出。"""
        api_response = {
            "results": [
                {
                    "title": "Let It Be",
                    "asin": "B0ASINONLY1",
                }
            ]
        }
        result = _extract_isrc_map_from_api_response(api_response)
        assert result == {"let it be": {"isrc": None, "asin": "B0ASINONLY1"}}

    def test_empty_response(self) -> None:
        """空のレスポンスでは空辞書を返す。"""
        assert _extract_isrc_map_from_api_response({}) == {}
        assert _extract_isrc_map_from_api_response({"data": []}) == {}

    def test_no_title_skipped(self) -> None:
        """タイトルがないアイテムは無視される。"""
        api_response = {
            "items": [
                {"isrc": "GBUM71029604", "asin": "B01N5XY2WQ"},
            ]
        }
        result = _extract_isrc_map_from_api_response(api_response)
        assert result == {}
