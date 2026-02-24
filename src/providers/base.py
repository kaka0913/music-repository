from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import Track


class AuthenticationError(Exception):
    """認証エラーを表すカスタム例外"""


class MusicProvider(ABC):
    """音楽サービスプロバイダーの共通インターフェース"""

    @abstractmethod
    def authenticate(self) -> None:
        """認証を実行。失敗時は AuthenticationError を送出。"""

    @abstractmethod
    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        """指定プレイリストの全楽曲を取得。"""

    @abstractmethod
    def add_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストに楽曲を追加。"""

    @abstractmethod
    def remove_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストから楽曲を削除。"""

    @abstractmethod
    def search_track(self, title: str, artist: str) -> Track | None:
        """曲名+アーティスト名で楽曲を検索（ISRCフォールバック用）。"""
