from __future__ import annotations

import logging

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from src.models import Track
from src.providers.base import AuthenticationError, MusicProvider
from src.utils.retry import NetworkError, RateLimitError, retry_with_backoff
from src.utils.secret_manager import get_secret

logger = logging.getLogger(__name__)


class SpotifyProvider(MusicProvider):
    """Spotify Web API を利用した MusicProvider 実装。"""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str = "https://github.com/callback"):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._sp: spotipy.Spotify | None = None

    def authenticate(self) -> None:
        """Secret Manager からリフレッシュトークンを取得し、spotipy クライアントを初期化。"""
        try:
            refresh_token = get_secret("spotify-refresh-token")
            auth_manager = SpotifyOAuth(
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=self._redirect_uri,
                scope="playlist-read-private playlist-modify-private playlist-modify-public user-library-read",
            )
            # リフレッシュトークンで新しいアクセストークンを取得
            token_info = auth_manager.refresh_access_token(refresh_token)
            self._sp = spotipy.Spotify(auth=token_info["access_token"])
            logger.info("Spotify authentication successful")
        except Exception as e:
            raise AuthenticationError(f"Spotify authentication failed: {e}") from e

    def _ensure_authenticated(self) -> spotipy.Spotify:
        if self._sp is None:
            raise AuthenticationError("Spotify client not initialized. Call authenticate() first.")
        return self._sp

    @retry_with_backoff()
    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        """プレイリストの全楽曲を取得。ページネーション対応。

        playlist_id が "liked" の場合、Liked Songs (お気に入りの曲) を取得する。
        """
        if playlist_id == "liked":
            return self._get_liked_tracks()

        sp = self._ensure_authenticated()
        tracks: list[Track] = []
        offset = 0
        limit = 100

        try:
            while True:
                results = sp.playlist_items(
                    playlist_id, offset=offset, limit=limit,
                    fields="items(added_at,track(name,artists,album,external_ids,uri,id)),next"
                )
                items = results.get("items", [])
                if not items:
                    break

                for item in items:
                    track_data = item.get("track")
                    if not track_data:
                        continue

                    isrc = None
                    external_ids = track_data.get("external_ids", {})
                    if external_ids:
                        isrc = external_ids.get("isrc")

                    artists = track_data.get("artists", [])
                    artist_name = artists[0]["name"] if artists else "Unknown"

                    album_data = track_data.get("album", {})
                    album_name = album_data.get("name", "") if isinstance(album_data, dict) else ""

                    tracks.append(Track(
                        isrc=isrc,
                        title=track_data.get("name", ""),
                        artist=artist_name,
                        album=album_name,
                        service_ids={"spotify": track_data.get("id")},
                        added_at=item.get("added_at"),
                    ))

                if results.get("next") is None:
                    break
                offset += limit
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

        logger.info("Retrieved %d tracks from Spotify playlist %s", len(tracks), playlist_id)
        return tracks

    def _get_liked_tracks(self) -> list[Track]:
        """Liked Songs (お気に入りの曲) を全曲取得。"""
        sp = self._ensure_authenticated()
        tracks: list[Track] = []
        offset = 0
        limit = 50

        while True:
            results = sp.current_user_saved_tracks(limit=limit, offset=offset)
            items = results.get("items", [])
            if not items:
                break

            for item in items:
                track_data = item.get("track")
                if not track_data:
                    continue

                isrc = None
                external_ids = track_data.get("external_ids", {})
                if external_ids:
                    isrc = external_ids.get("isrc")

                artists = track_data.get("artists", [])
                artist_name = artists[0]["name"] if artists else "Unknown"
                album_data = track_data.get("album", {})
                album_name = album_data.get("name", "") if isinstance(album_data, dict) else ""

                tracks.append(Track(
                    isrc=isrc,
                    title=track_data.get("name", ""),
                    artist=artist_name,
                    album=album_name,
                    service_ids={"spotify": track_data.get("id")},
                    added_at=item.get("added_at"),
                ))

            if results.get("next") is None:
                break
            offset += limit

        logger.info("Retrieved %d Liked Songs from Spotify", len(tracks))
        return tracks

    @retry_with_backoff()
    def add_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストに楽曲を追加。Spotify URI を指定。

        playlist_id が "liked" の場合、Liked Songs に追加する。
        """
        if playlist_id == "liked":
            return self._add_liked_tracks(tracks)

        sp = self._ensure_authenticated()
        # Spotify API は一度に最大100曲まで
        uris = []
        for track in tracks:
            spotify_id = track.service_ids.get("spotify")
            if spotify_id:
                uris.append(f"spotify:track:{spotify_id}")

        try:
            for i in range(0, len(uris), 100):
                batch = uris[i:i + 100]
                sp.playlist_add_items(playlist_id, batch)
                logger.info("Added %d tracks to Spotify playlist %s", len(batch), playlist_id)
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

    @retry_with_backoff()
    def remove_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストから楽曲を削除。

        playlist_id が "liked" の場合、Liked Songs から削除する。
        """
        if playlist_id == "liked":
            return self._remove_liked_tracks(tracks)

        sp = self._ensure_authenticated()
        uris = []
        for track in tracks:
            spotify_id = track.service_ids.get("spotify")
            if spotify_id:
                uris.append(f"spotify:track:{spotify_id}")

        try:
            for i in range(0, len(uris), 100):
                batch = uris[i:i + 100]
                sp.playlist_remove_all_occurrences_of_items(playlist_id, batch)
                logger.info("Removed %d tracks from Spotify playlist %s", len(batch), playlist_id)
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

    def _add_liked_tracks(self, tracks: list[Track]) -> None:
        """Liked Songs に楽曲を追加。"""
        sp = self._ensure_authenticated()
        ids = []
        for track in tracks:
            spotify_id = track.service_ids.get("spotify")
            if spotify_id:
                ids.append(spotify_id)

        try:
            for i in range(0, len(ids), 50):
                batch = ids[i:i + 50]
                sp.current_user_saved_tracks_add(batch)
                logger.info("Added %d tracks to Spotify Liked Songs", len(batch))
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

    def _remove_liked_tracks(self, tracks: list[Track]) -> None:
        """Liked Songs から楽曲を削除。"""
        sp = self._ensure_authenticated()
        ids = []
        for track in tracks:
            spotify_id = track.service_ids.get("spotify")
            if spotify_id:
                ids.append(spotify_id)

        try:
            for i in range(0, len(ids), 50):
                batch = ids[i:i + 50]
                sp.current_user_saved_tracks_delete(batch)
                logger.info("Removed %d tracks from Spotify Liked Songs", len(batch))
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

    @retry_with_backoff()
    def search_track(self, title: str, artist: str) -> Track | None:
        """ISRC 検索 → フォールバックで曲名+アーティスト検索。"""
        sp = self._ensure_authenticated()
        query = f"track:{title} artist:{artist}"

        try:
            results = sp.search(q=query, type="track", limit=1)
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

        items = results.get("tracks", {}).get("items", [])
        if not items:
            return None

        item = items[0]
        isrc = item.get("external_ids", {}).get("isrc")
        artists = item.get("artists", [])
        artist_name = artists[0]["name"] if artists else "Unknown"
        album_data = item.get("album", {})

        return Track(
            isrc=isrc,
            title=item.get("name", ""),
            artist=artist_name,
            album=album_data.get("name", "") if isinstance(album_data, dict) else "",
            service_ids={"spotify": item.get("id")},
        )

    @retry_with_backoff()
    def get_all_playlists(self) -> list[tuple[str, str]]:
        """ユーザーの全プレイリストを取得。"""
        sp = self._ensure_authenticated()
        playlists: list[tuple[str, str]] = []
        offset = 0
        limit = 50

        try:
            while True:
                results = sp.current_user_playlists(limit=limit, offset=offset)
                items = results.get("items", [])
                if not items:
                    break
                for item in items:
                    name = item.get("name", "")
                    playlist_id = item.get("id", "")
                    if name and playlist_id:
                        playlists.append((name, playlist_id))
                if results.get("next") is None:
                    break
                offset += limit
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e

        logger.info("Discovered %d playlists from Spotify", len(playlists))
        return playlists

    @retry_with_backoff()
    def create_playlist(self, name: str) -> str:
        """新しい空プレイリストを作成し、その ID を返す。"""
        sp = self._ensure_authenticated()
        try:
            user_id = sp.current_user()["id"]
            result = sp.user_playlist_create(
                user=user_id,
                name=name,
                public=False,
                description="Auto-created by Music Playlist Hub",
            )
            playlist_id = result["id"]
            logger.info("Created Spotify playlist '%s' (id=%s)", name, playlist_id)
            return playlist_id
        except SpotifyException as e:
            if e.http_status == 429:
                raise RateLimitError(f"Spotify rate limit exceeded: {e}") from e
            raise
        except (ConnectionError, TimeoutError) as e:
            raise NetworkError(f"Spotify network error: {e}") from e
