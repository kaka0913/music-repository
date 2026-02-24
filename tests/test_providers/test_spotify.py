from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.models import Track
from src.providers.base import AuthenticationError
from src.providers.spotify import SpotifyProvider


@pytest.fixture
def provider() -> SpotifyProvider:
    """認証済み状態の SpotifyProvider を返すフィクスチャ。"""
    p = SpotifyProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )
    p._sp = MagicMock()
    return p


class TestAuthenticate:
    """authenticate() メソッドのテスト。"""

    @patch("src.providers.spotify.SpotifyOAuth")
    @patch("src.providers.spotify.get_secret")
    def test_authenticate_success(self, mock_get_secret: MagicMock, mock_oauth_cls: MagicMock) -> None:
        """get_secret と SpotifyOAuth.refresh_access_token をモックして認証成功を確認。"""
        mock_get_secret.return_value = "fake-refresh-token"
        mock_auth_manager = MagicMock()
        mock_auth_manager.refresh_access_token.return_value = {
            "access_token": "fake-access-token",
        }
        mock_oauth_cls.return_value = mock_auth_manager

        provider = SpotifyProvider(
            client_id="test-client-id",
            client_secret="test-client-secret",
        )
        provider.authenticate()

        mock_get_secret.assert_called_once_with("spotify-refresh-token")
        mock_oauth_cls.assert_called_once_with(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="http://localhost:8888/callback",
            scope="playlist-read-private playlist-modify-private playlist-modify-public",
        )
        mock_auth_manager.refresh_access_token.assert_called_once_with("fake-refresh-token")
        assert provider._sp is not None

    @patch("src.providers.spotify.get_secret")
    def test_authenticate_failure(self, mock_get_secret: MagicMock) -> None:
        """get_secret が例外を投げた場合に AuthenticationError が発生することを確認。"""
        mock_get_secret.side_effect = Exception("Secret not found")

        provider = SpotifyProvider(
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

        with pytest.raises(AuthenticationError, match="Spotify authentication failed"):
            provider.authenticate()


class TestGetPlaylistTracks:
    """get_playlist_tracks() メソッドのテスト。"""

    def test_get_playlist_tracks(self, provider: SpotifyProvider) -> None:
        """sp.playlist_items をモックして Track リストが正しく返されることを確認。"""
        provider._sp.playlist_items.return_value = {
            "items": [
                {
                    "added_at": "2024-01-15T10:30:00Z",
                    "track": {
                        "name": "Bohemian Rhapsody",
                        "artists": [{"name": "Queen"}],
                        "album": {"name": "A Night at the Opera"},
                        "external_ids": {"isrc": "GBUM71029604"},
                        "uri": "spotify:track:4u7EnebtmKWzUH433cf5Qv",
                        "id": "4u7EnebtmKWzUH433cf5Qv",
                    },
                },
                {
                    "added_at": "2024-01-16T12:00:00Z",
                    "track": {
                        "name": "Imagine",
                        "artists": [{"name": "John Lennon"}],
                        "album": {"name": "Imagine"},
                        "external_ids": {"isrc": "USRC17607839"},
                        "uri": "spotify:track:7pKfPomDEeI4TPT6EOYjn9",
                        "id": "7pKfPomDEeI4TPT6EOYjn9",
                    },
                },
            ],
            "next": None,
        }

        tracks = provider.get_playlist_tracks("playlist-123")

        assert len(tracks) == 2

        assert tracks[0].isrc == "GBUM71029604"
        assert tracks[0].title == "Bohemian Rhapsody"
        assert tracks[0].artist == "Queen"
        assert tracks[0].album == "A Night at the Opera"
        assert tracks[0].service_ids == {"spotify": "4u7EnebtmKWzUH433cf5Qv"}
        assert tracks[0].added_at == "2024-01-15T10:30:00Z"

        assert tracks[1].isrc == "USRC17607839"
        assert tracks[1].title == "Imagine"
        assert tracks[1].artist == "John Lennon"
        assert tracks[1].album == "Imagine"
        assert tracks[1].service_ids == {"spotify": "7pKfPomDEeI4TPT6EOYjn9"}
        assert tracks[1].added_at == "2024-01-16T12:00:00Z"


class TestAddTracks:
    """add_tracks() メソッドのテスト。"""

    def test_add_tracks(self, provider: SpotifyProvider) -> None:
        """sp.playlist_add_items が正しい URI で呼ばれることを確認。"""
        tracks = [
            Track(
                isrc="GBUM71029604",
                title="Bohemian Rhapsody",
                artist="Queen",
                album="A Night at the Opera",
                service_ids={"spotify": "4u7EnebtmKWzUH433cf5Qv"},
            ),
            Track(
                isrc="USRC17607839",
                title="Imagine",
                artist="John Lennon",
                album="Imagine",
                service_ids={"spotify": "7pKfPomDEeI4TPT6EOYjn9"},
            ),
        ]

        provider.add_tracks("playlist-123", tracks)

        provider._sp.playlist_add_items.assert_called_once_with(
            "playlist-123",
            [
                "spotify:track:4u7EnebtmKWzUH433cf5Qv",
                "spotify:track:7pKfPomDEeI4TPT6EOYjn9",
            ],
        )


class TestRemoveTracks:
    """remove_tracks() メソッドのテスト。"""

    def test_remove_tracks(self, provider: SpotifyProvider) -> None:
        """sp.playlist_remove_all_occurrences_of_items が正しい URI で呼ばれることを確認。"""
        tracks = [
            Track(
                isrc="GBUM71029604",
                title="Bohemian Rhapsody",
                artist="Queen",
                album="A Night at the Opera",
                service_ids={"spotify": "4u7EnebtmKWzUH433cf5Qv"},
            ),
            Track(
                isrc="USRC17607839",
                title="Imagine",
                artist="John Lennon",
                album="Imagine",
                service_ids={"spotify": "7pKfPomDEeI4TPT6EOYjn9"},
            ),
        ]

        provider.remove_tracks("playlist-123", tracks)

        provider._sp.playlist_remove_all_occurrences_of_items.assert_called_once_with(
            "playlist-123",
            [
                "spotify:track:4u7EnebtmKWzUH433cf5Qv",
                "spotify:track:7pKfPomDEeI4TPT6EOYjn9",
            ],
        )


class TestSearchTrack:
    """search_track() メソッドのテスト。"""

    def test_search_track_found(self, provider: SpotifyProvider) -> None:
        """sp.search をモックして Track が返されることを確認。"""
        provider._sp.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "name": "Bohemian Rhapsody",
                        "artists": [{"name": "Queen"}],
                        "album": {"name": "A Night at the Opera"},
                        "external_ids": {"isrc": "GBUM71029604"},
                        "id": "4u7EnebtmKWzUH433cf5Qv",
                    }
                ]
            }
        }

        result = provider.search_track("Bohemian Rhapsody", "Queen")

        assert result is not None
        assert result.isrc == "GBUM71029604"
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.album == "A Night at the Opera"
        assert result.service_ids == {"spotify": "4u7EnebtmKWzUH433cf5Qv"}

        provider._sp.search.assert_called_once_with(
            q="track:Bohemian Rhapsody artist:Queen",
            type="track",
            limit=1,
        )

    def test_search_track_not_found(self, provider: SpotifyProvider) -> None:
        """検索結果が空の場合に None が返ることを確認。"""
        provider._sp.search.return_value = {
            "tracks": {
                "items": []
            }
        }

        result = provider.search_track("Nonexistent Song", "Unknown Artist")

        assert result is None
