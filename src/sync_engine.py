from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.models import PlaylistConfig, SyncResult, Track
from src.providers.base import MusicProvider
from src.utils.isrc import find_match

logger = logging.getLogger(__name__)

STATE_DIR = Path("state")


def load_state(playlist_name: str) -> dict:
    """state/{playlist_name}.json の読み込み。初回は空状態を返す。"""
    state_file = STATE_DIR / f"{playlist_name}.json"
    if not state_file.exists():
        logger.info("No existing state for '%s'. Starting fresh.", playlist_name)
        return {
            "playlist_name": playlist_name,
            "last_synced_at": None,
            "tracks": [],
            "unmatched": [],
        }

    with open(state_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(playlist_name: str, state: dict) -> None:
    """状態ファイルの書き出し。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{playlist_name}.json"

    state["last_synced_at"] = datetime.now(timezone.utc).isoformat()

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    logger.info("State saved for '%s'", playlist_name)


def _tracks_to_isrc_map(tracks: list[dict | Track]) -> dict[str, dict | Track]:
    """トラックリストを ISRC をキーとした辞書に変換。ISRC が None のものは service_id ベースのキーを使う。"""
    result = {}
    for track in tracks:
        if isinstance(track, Track):
            key = track.isrc or f"_no_isrc_{track.title}_{track.artist}"
            result[key] = track
        else:
            key = track.get("isrc") or f"_no_isrc_{track.get('title', '')}_{track.get('artist', '')}"
            result[key] = track
    return result


def compute_diff(
    previous_tracks: list[dict], current_tracks: list[Track]
) -> tuple[list[Track], list[dict]]:
    """ISRC ベースで差分計算。(added, removed) を返す。"""
    prev_map = _tracks_to_isrc_map(previous_tracks)
    curr_map = _tracks_to_isrc_map(current_tracks)

    prev_keys = set(prev_map.keys())
    curr_keys = set(curr_map.keys())

    added_keys = curr_keys - prev_keys
    removed_keys = prev_keys - curr_keys

    added = [curr_map[k] for k in added_keys]
    removed = [prev_map[k] for k in removed_keys]

    return added, removed


def resolve_conflicts(
    diffs_by_service: dict[str, tuple[list[Track], list[dict]]]
) -> tuple[list[Track], list[dict]]:
    """
    タイムスタンプ優先の競合解決。

    diffs_by_service: {"spotify": (added, removed), "apple_music": (added, removed), ...}

    同一ISRCについて:
      サービスAで追加 & サービスBで削除 の場合:
        1. 両方の added_at タイムスタンプを比較 → 新しい方を採用
        2. 片方のみタイムスタンプあり → その方を採用
        3. 両方ともなし → 追加を優先（安全策）

    返り値: (to_add, to_remove) 最終的に反映すべき追加・削除リスト
    """
    all_added: dict[str, Track] = {}
    all_removed: dict[str, dict] = {}

    # 全サービスの追加・削除を集約
    for service, (added, removed) in diffs_by_service.items():
        for track in added:
            key = track.isrc or f"_no_isrc_{track.title}_{track.artist}"
            if key not in all_added:
                all_added[key] = track
            else:
                # より新しい added_at を持つ方を採用
                existing = all_added[key]
                if track.added_at and existing.added_at:
                    if track.added_at > existing.added_at:
                        all_added[key] = track
                elif track.added_at:
                    all_added[key] = track

        for track in removed:
            if isinstance(track, Track):
                key = track.isrc or f"_no_isrc_{track.title}_{track.artist}"
            else:
                key = track.get("isrc") or f"_no_isrc_{track.get('title', '')}_{track.get('artist', '')}"
            if key not in all_removed:
                all_removed[key] = track

    # 競合解決: 追加と削除の両方に存在するISRC
    conflict_keys = set(all_added.keys()) & set(all_removed.keys())

    to_add = dict(all_added)
    to_remove = dict(all_removed)

    for key in conflict_keys:
        added_track = all_added[key]
        removed_track = all_removed[key]

        added_at = added_track.added_at
        removed_at = None
        if isinstance(removed_track, Track):
            removed_at = removed_track.added_at
        elif isinstance(removed_track, dict):
            removed_at = removed_track.get("added_at")

        if added_at and removed_at:
            # 新しい方の操作を採用
            if added_at >= removed_at:
                # 追加を採用、削除を取り消し
                del to_remove[key]
            else:
                # 削除を採用、追加を取り消し
                del to_add[key]
        elif added_at:
            # 追加側のみタイムスタンプあり → 追加を採用
            del to_remove[key]
        elif removed_at:
            # 削除側のみタイムスタンプあり → 削除を採用
            del to_add[key]
        else:
            # 両方ともなし → 追加を優先（安全策）
            del to_remove[key]

    return list(to_add.values()), list(to_remove.values())


def _track_to_dict(track: Track) -> dict:
    """Track dataclass を辞書に変換する。"""
    return asdict(track)


def sync_playlist(
    playlist_config: PlaylistConfig,
    providers: dict[str, MusicProvider],
) -> SyncResult:
    """1プレイリストの同期を実行する。

    1. 各サービスから現在の曲目を取得
    2. 前回状態との差分を計算
    3. 競合を解決
    4. 各サービスへ反映
    5. 状態を保存
    """
    result = SyncResult()
    playlist_name = playlist_config.name

    # サービスごとのプレイリストID/URLマッピング
    service_playlist_ids = {}
    if playlist_config.spotify and "playlist_id" in playlist_config.spotify:
        service_playlist_ids["spotify"] = playlist_config.spotify["playlist_id"]
    if playlist_config.apple_music and "playlist_url" in playlist_config.apple_music:
        service_playlist_ids["apple_music"] = playlist_config.apple_music["playlist_url"]
    if playlist_config.amazon_music and "playlist_url" in playlist_config.amazon_music:
        service_playlist_ids["amazon_music"] = playlist_config.amazon_music["playlist_url"]

    # 1. 各サービスから現在の曲目を取得
    current_tracks_by_service: dict[str, list[Track]] = {}
    for service_name, playlist_id in service_playlist_ids.items():
        if service_name not in providers:
            continue
        try:
            tracks = providers[service_name].get_playlist_tracks(playlist_id)
            current_tracks_by_service[service_name] = tracks
            logger.info("[%s] %s: %d tracks", playlist_name, service_name, len(tracks))
        except Exception as e:
            error_msg = f"{service_name}: Failed to get tracks - {e}"
            logger.error("[%s] %s", playlist_name, error_msg)
            result.errors.append(error_msg)

    if not current_tracks_by_service:
        result.errors.append("No tracks retrieved from any service")
        return result

    # 2. 前回状態の読み込み & 差分計算
    state = load_state(playlist_name)
    previous_tracks = state.get("tracks", [])

    diffs_by_service: dict[str, tuple[list[Track], list[dict]]] = {}
    for service_name, tracks in current_tracks_by_service.items():
        added, removed = compute_diff(previous_tracks, tracks)
        diffs_by_service[service_name] = (added, removed)
        logger.info("[%s] %s diff: +%d -%d", playlist_name, service_name, len(added), len(removed))

    # 3. 競合解決
    to_add, to_remove = resolve_conflicts(diffs_by_service)
    logger.info("[%s] After conflict resolution: +%d -%d", playlist_name, len(to_add), len(to_remove))

    # 4. 各サービスへ反映
    for service_name, provider in providers.items():
        if service_name not in service_playlist_ids:
            continue
        playlist_id = service_playlist_ids[service_name]

        # 追加: 他サービスで追加された曲をこのサービスにも追加
        tracks_to_add_here: list[Track] = []
        for track in to_add:
            # このサービスに既に存在する場合はスキップ
            if service_name in current_tracks_by_service:
                existing_isrcs = {
                    t.isrc or f"_no_isrc_{t.title}_{t.artist}"
                    for t in current_tracks_by_service[service_name]
                }
                track_key = track.isrc or f"_no_isrc_{track.title}_{track.artist}"
                if track_key in existing_isrcs:
                    continue

            # このサービスでの楽曲IDを検索
            matched = find_match(track, provider, playlist_id)
            if matched:
                tracks_to_add_here.append(matched)
            else:
                result.unmatched.append({
                    "source_service": service_name,
                    "title": track.title,
                    "artist": track.artist,
                    "isrc": track.isrc,
                    "reason": f"No match found on {service_name}",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        if tracks_to_add_here:
            try:
                provider.add_tracks(playlist_id, tracks_to_add_here)
                result.added.extend(tracks_to_add_here)
                logger.info("[%s] Added %d tracks to %s", playlist_name, len(tracks_to_add_here), service_name)
            except Exception as e:
                result.errors.append(f"{service_name}: Failed to add tracks - {e}")

        # 削除
        tracks_to_remove_here: list[Track] = []
        for track in to_remove:
            if service_name in current_tracks_by_service:
                existing_isrcs = {
                    t.isrc or f"_no_isrc_{t.title}_{t.artist}"
                    for t in current_tracks_by_service[service_name]
                }
                track_key = track.get("isrc") if isinstance(track, dict) else track.isrc
                if not track_key:
                    t = track if isinstance(track, dict) else track
                    title = t.get("title", "") if isinstance(t, dict) else t.title
                    artist = t.get("artist", "") if isinstance(t, dict) else t.artist
                    track_key = f"_no_isrc_{title}_{artist}"
                if track_key in existing_isrcs:
                    if isinstance(track, dict):
                        tracks_to_remove_here.append(Track(
                            isrc=track.get("isrc"),
                            title=track.get("title", ""),
                            artist=track.get("artist", ""),
                            album=track.get("album", ""),
                            service_ids=track.get("service_ids", {}),
                        ))
                    else:
                        tracks_to_remove_here.append(track)

        if tracks_to_remove_here:
            try:
                provider.remove_tracks(playlist_id, tracks_to_remove_here)
                result.removed.extend(tracks_to_remove_here)
                logger.info("[%s] Removed %d tracks from %s", playlist_name, len(tracks_to_remove_here), service_name)
            except Exception as e:
                result.errors.append(f"{service_name}: Failed to remove tracks - {e}")

    # 5. 状態を更新・保存
    # 全サービスのトラックを統合して最新状態とする
    merged_tracks: dict[str, dict] = {}
    for service_name, tracks in current_tracks_by_service.items():
        for track in tracks:
            key = track.isrc or f"_no_isrc_{track.title}_{track.artist}"
            if key not in merged_tracks:
                merged_tracks[key] = _track_to_dict(track)
            else:
                # service_ids をマージ
                merged_tracks[key]["service_ids"].update(track.service_ids)

    state["tracks"] = list(merged_tracks.values())
    state["unmatched"] = result.unmatched
    save_state(playlist_name, state)

    return result
