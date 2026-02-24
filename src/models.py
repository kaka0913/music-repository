from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Track:
    """楽曲情報を表すデータクラス。"""

    isrc: str | None
    title: str
    artist: str
    album: str
    service_ids: dict[str, str | None] = field(default_factory=dict)
    added_at: str | None = None


@dataclass
class PlaylistConfig:
    """プレイリスト設定を表すデータクラス。"""

    name: str
    spotify: dict[str, str] | None = None
    apple_music: dict[str, str] | None = None
    amazon_music: dict[str, str] | None = None


@dataclass
class SyncResult:
    """同期結果を表すデータクラス。"""

    added: list[Track] = field(default_factory=list)
    removed: list[Track] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PlaylistInfo:
    """発見されたプレイリスト情報。"""

    name: str
    service_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class SyncConfig:
    """トップレベルの同期設定。"""

    auto_discover: bool = False
    playlists: list[PlaylistConfig] = field(default_factory=list)
