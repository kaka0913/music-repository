from __future__ import annotations

import logging

from src.models import Track
from src.providers.base import MusicProvider

logger = logging.getLogger(__name__)


def match_by_isrc(track: Track, provider: MusicProvider, playlist_id: str) -> Track | None:
    """ISRC でプロバイダー内の楽曲を検索する。"""
    if not track.isrc:
        return None

    # プロバイダーの search_track を利用して ISRC で検索
    # 多くのAPIではISRC検索がサポートされているが、
    # search_track は title+artist ベースなので、ここでは直接的なISRC検索を試みる
    # 実際にはプロバイダーごとの実装に依存する
    result = provider.search_track(track.title, track.artist)
    if result and result.isrc == track.isrc:
        logger.debug("ISRC match found for '%s' by %s", track.title, track.artist)
        return result

    return None


def match_by_metadata(track: Track, provider: MusicProvider) -> Track | None:
    """曲名+アーティスト名でフォールバック検索する。"""
    result = provider.search_track(track.title, track.artist)
    if result:
        logger.debug("Metadata match found for '%s' by %s", track.title, track.artist)
        return result

    return None


def find_match(track: Track, provider: MusicProvider, playlist_id: str = "") -> Track | None:
    """ISRC → メタデータの順にマッチを試行する統合関数。"""
    # 1. ISRC で検索
    matched = match_by_isrc(track, provider, playlist_id)
    if matched:
        return matched

    # 2. メタデータでフォールバック検索
    matched = match_by_metadata(track, provider)
    if matched:
        return matched

    logger.warning("No match found for '%s' by %s", track.title, track.artist)
    return None
