from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.models import Track
from src.providers.base import MusicProvider
from src.utils.isrc import find_match, match_by_isrc, match_by_metadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def provider() -> MagicMock:
    """MusicProvider のモックを返す。"""
    return MagicMock(spec=MusicProvider)


@pytest.fixture()
def sample_track() -> Track:
    """ISRC 付きのサンプル Track を返す。"""
    return Track(
        isrc="USAT21234567",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
    )


@pytest.fixture()
def track_without_isrc() -> Track:
    """ISRC なしのサンプル Track を返す。"""
    return Track(
        isrc=None,
        title="No ISRC Song",
        artist="Unknown Artist",
        album="Unknown Album",
    )


# ---------------------------------------------------------------------------
# match_by_isrc
# ---------------------------------------------------------------------------

class TestMatchByIsrc:
    def test_match_by_isrc_success(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """Track に ISRC があり、プロバイダーが同じ ISRC の Track を返す場合にマッチする。"""
        matched_track = Track(
            isrc="USAT21234567",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            service_ids={"spotify": "sp123"},
        )
        provider.search_track.return_value = matched_track

        result = match_by_isrc(sample_track, provider, playlist_id="pl1")

        assert result is matched_track
        provider.search_track.assert_called_once_with("Test Song", "Test Artist")

    def test_match_by_isrc_no_isrc(
        self, track_without_isrc: Track, provider: MagicMock
    ) -> None:
        """Track の ISRC が None の場合に None が返る。"""
        result = match_by_isrc(track_without_isrc, provider, playlist_id="pl1")

        assert result is None
        provider.search_track.assert_not_called()

    def test_match_by_isrc_different_isrc(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """プロバイダーが異なる ISRC の Track を返す場合に None が返る。"""
        different_track = Track(
            isrc="GBAYE9900001",
            title="Test Song",
            artist="Test Artist",
            album="Different Album",
        )
        provider.search_track.return_value = different_track

        result = match_by_isrc(sample_track, provider, playlist_id="pl1")

        assert result is None
        provider.search_track.assert_called_once_with("Test Song", "Test Artist")


# ---------------------------------------------------------------------------
# match_by_metadata
# ---------------------------------------------------------------------------

class TestMatchByMetadata:
    def test_match_by_metadata_success(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """search_track が結果を返す場合にマッチする。"""
        found_track = Track(
            isrc="USAT21234567",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
        )
        provider.search_track.return_value = found_track

        result = match_by_metadata(sample_track, provider)

        assert result is found_track
        provider.search_track.assert_called_once_with("Test Song", "Test Artist")

    def test_match_by_metadata_not_found(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """search_track が None を返す場合に None が返る。"""
        provider.search_track.return_value = None

        result = match_by_metadata(sample_track, provider)

        assert result is None
        provider.search_track.assert_called_once_with("Test Song", "Test Artist")


# ---------------------------------------------------------------------------
# find_match
# ---------------------------------------------------------------------------

class TestFindMatch:
    def test_find_match_isrc_first(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """ISRC マッチが成功すればそれを返す（メタデータ検索は呼ばれない）。"""
        isrc_matched = Track(
            isrc="USAT21234567",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
        )
        provider.search_track.return_value = isrc_matched

        result = find_match(sample_track, provider, playlist_id="pl1")

        assert result is isrc_matched
        # ISRC マッチで 1 回だけ呼ばれる
        provider.search_track.assert_called_once_with("Test Song", "Test Artist")

    def test_find_match_fallback_to_metadata(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """ISRC マッチ失敗後にメタデータマッチにフォールバックする。"""
        # 1 回目: ISRC 不一致の Track を返す → ISRC マッチ失敗
        # 2 回目: メタデータ検索で別の Track を返す → フォールバック成功
        metadata_matched = Track(
            isrc="GBAYE9900001",
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
        )
        provider.search_track.side_effect = [metadata_matched, metadata_matched]

        result = find_match(sample_track, provider, playlist_id="pl1")

        assert result is metadata_matched
        assert provider.search_track.call_count == 2

    def test_find_match_no_match(
        self, sample_track: Track, provider: MagicMock
    ) -> None:
        """両方失敗時に None が返る。"""
        provider.search_track.return_value = None

        result = find_match(sample_track, provider, playlist_id="pl1")

        assert result is None
        # ISRC 検索 + メタデータ検索 = 2 回
        assert provider.search_track.call_count == 2
