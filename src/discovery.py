from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path

from src.models import PlaylistConfig, PlaylistInfo, SyncConfig
from src.providers.base import MusicProvider

logger = logging.getLogger(__name__)

CACHE_FILE = Path("state/discovery_cache.json")


def normalize_name(name: str) -> str:
    """プレイリスト名の正規化。NFKC 正規化 + 小文字化 + 前後空白除去。"""
    return unicodedata.normalize("NFKC", name).strip().lower()


def collect_all_playlists(
    providers: dict[str, MusicProvider],
) -> dict[str, list[tuple[str, str]]]:
    """全プロバイダーからプレイリスト一覧を取得。

    Returns:
        {"spotify": [("name", "id"), ...], "apple_music": [...], ...}
    """
    result: dict[str, list[tuple[str, str]]] = {}
    for service_name, provider in providers.items():
        try:
            playlists = provider.get_all_playlists()
            result[service_name] = playlists
            logger.info("Collected %d playlists from %s", len(playlists), service_name)
        except Exception as e:
            logger.error("Failed to get playlists from %s: %s", service_name, e)
            result[service_name] = []
    return result


def match_playlists_by_name(
    all_playlists: dict[str, list[tuple[str, str]]],
) -> list[PlaylistInfo]:
    """名前ベースでクロスサービスマッチング。

    正規化した名前が一致するプレイリストを統合する。
    """
    # normalized_name -> PlaylistInfo
    merged: dict[str, PlaylistInfo] = {}

    for service_name, playlists in all_playlists.items():
        for name, playlist_id in playlists:
            key = normalize_name(name)
            if key not in merged:
                merged[key] = PlaylistInfo(name=name, service_ids={})
            merged[key].service_ids[service_name] = playlist_id

    result = list(merged.values())
    logger.info("Matched %d unique playlists across services", len(result))
    return result


def create_missing_playlists(
    matched: list[PlaylistInfo],
    providers: dict[str, MusicProvider],
    dry_run: bool = False,
) -> list[PlaylistInfo]:
    """存在しないサービスにプレイリストを自動作成。

    全 provider に対して、まだ service_ids に含まれていないサービスのプレイリストを作成する。
    dry_run=True の場合はログ出力のみで実際の作成は行わない。
    """
    service_names = set(providers.keys())

    for info in matched:
        missing = service_names - set(info.service_ids.keys())
        for service_name in missing:
            if dry_run:
                logger.info(
                    "DRY RUN: Would create playlist '%s' on %s (skipped)",
                    info.name, service_name,
                )
                continue
            try:
                new_id = providers[service_name].create_playlist(info.name)
                info.service_ids[service_name] = new_id
                logger.info(
                    "Created playlist '%s' on %s (id=%s)",
                    info.name, service_name, new_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to create playlist '%s' on %s: %s",
                    info.name, service_name, e,
                )

    return matched


def merge_with_manual(
    discovered: list[PlaylistInfo],
    manual_playlists: list[PlaylistConfig],
) -> list[PlaylistConfig]:
    """手動設定（playlists.yaml）との統合。手動設定が優先。"""
    # 手動設定を正規化名でインデックス
    manual_by_name: dict[str, PlaylistConfig] = {
        normalize_name(p.name): p for p in manual_playlists
    }

    result: list[PlaylistConfig] = []

    for info in discovered:
        key = normalize_name(info.name)

        if key in manual_by_name:
            # 手動設定があればそちらを優先しつつ、発見したIDで補完
            manual = manual_by_name.pop(key)
            if not manual.spotify and "spotify" in info.service_ids:
                manual.spotify = {"playlist_id": info.service_ids["spotify"]}
            if not manual.apple_music and "apple_music" in info.service_ids:
                manual.apple_music = {"playlist_url": info.service_ids["apple_music"]}
            if not manual.amazon_music and "amazon_music" in info.service_ids:
                manual.amazon_music = {"playlist_url": info.service_ids["amazon_music"]}
            result.append(manual)
        else:
            # 発見のみ
            config = PlaylistConfig(
                name=info.name,
                spotify={"playlist_id": info.service_ids["spotify"]}
                if "spotify" in info.service_ids else None,
                apple_music={"playlist_url": info.service_ids["apple_music"]}
                if "apple_music" in info.service_ids else None,
                amazon_music={"playlist_url": info.service_ids["amazon_music"]}
                if "amazon_music" in info.service_ids else None,
            )
            result.append(config)

    # 手動設定のみ（発見されなかったもの）も追加
    for manual in manual_by_name.values():
        result.append(manual)

    return result


def save_discovery_cache(discovered: list[PlaylistInfo]) -> None:
    """発見結果をキャッシュに保存。"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {"name": info.name, "service_ids": info.service_ids}
        for info in discovered
    ]
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Discovery cache saved to %s", CACHE_FILE)


def discover_and_merge_playlists(
    providers: dict[str, MusicProvider],
    manual_playlists: list[PlaylistConfig],
    dry_run: bool = False,
) -> list[PlaylistConfig]:
    """自動発見パイプラインのメインエントリポイント。

    1. 全プロバイダーからプレイリスト一覧を取得
    2. 名前ベースでマッチング
    3. 存在しないサービスにプレイリストを自動作成 (dry_run 時はスキップ)
    4. 手動設定と統合
    5. キャッシュ保存
    """
    # 1. 収集
    all_playlists = collect_all_playlists(providers)

    # 2. マッチング
    matched = match_playlists_by_name(all_playlists)

    # 3. 不足分を作成
    matched = create_missing_playlists(matched, providers, dry_run=dry_run)

    # 4. キャッシュ保存
    save_discovery_cache(matched)

    # 5. 手動設定と統合
    merged = merge_with_manual(matched, manual_playlists)

    logger.info("Discovery complete: %d playlists to sync", len(merged))
    return merged
