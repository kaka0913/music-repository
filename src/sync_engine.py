from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.models import Track

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
