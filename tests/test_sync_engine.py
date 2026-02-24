from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import Track
from src.sync_engine import (
    STATE_DIR,
    compute_diff,
    load_state,
    resolve_conflicts,
    save_state,
)


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


def test_load_state_no_file(tmp_path: Path) -> None:
    """state ファイルが存在しない場合、空状態が返ることを確認。"""
    with patch("src.sync_engine.STATE_DIR", tmp_path):
        state = load_state("my_playlist")

    assert state["playlist_name"] == "my_playlist"
    assert state["last_synced_at"] is None
    assert state["tracks"] == []
    assert state["unmatched"] == []


def test_load_state_existing(tmp_path: Path) -> None:
    """state ファイルが存在する場合、正しく読み込まれることを確認。"""
    existing = {
        "playlist_name": "rock_hits",
        "last_synced_at": "2025-01-01T00:00:00+00:00",
        "tracks": [
            {"isrc": "US1234567890", "title": "Song A", "artist": "Artist A"}
        ],
        "unmatched": [],
    }
    state_file = tmp_path / "rock_hits.json"
    state_file.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    with patch("src.sync_engine.STATE_DIR", tmp_path):
        state = load_state("rock_hits")

    assert state["playlist_name"] == "rock_hits"
    assert state["last_synced_at"] == "2025-01-01T00:00:00+00:00"
    assert len(state["tracks"]) == 1
    assert state["tracks"][0]["isrc"] == "US1234567890"


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------


def test_save_state(tmp_path: Path) -> None:
    """save_state 後にファイルが作成され、last_synced_at が設定されていることを確認。"""
    state = {
        "playlist_name": "jazz_favs",
        "last_synced_at": None,
        "tracks": [],
        "unmatched": [],
    }

    with patch("src.sync_engine.STATE_DIR", tmp_path):
        save_state("jazz_favs", state)

    state_file = tmp_path / "jazz_favs.json"
    assert state_file.exists()

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["playlist_name"] == "jazz_favs"
    assert saved["last_synced_at"] is not None


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


def test_compute_diff_added() -> None:
    """新曲が added に含まれることを確認。"""
    previous: list[dict] = []
    current = [
        Track(
            isrc="US0000000001",
            title="New Song",
            artist="New Artist",
            album="New Album",
        ),
    ]

    added, removed = compute_diff(previous, current)

    assert len(added) == 1
    assert added[0].isrc == "US0000000001"
    assert len(removed) == 0


def test_compute_diff_removed() -> None:
    """削除された曲が removed に含まれることを確認。"""
    previous: list[dict] = [
        {"isrc": "US0000000001", "title": "Old Song", "artist": "Old Artist"},
    ]
    current: list[Track] = []

    added, removed = compute_diff(previous, current)

    assert len(added) == 0
    assert len(removed) == 1
    assert removed[0]["isrc"] == "US0000000001"


def test_compute_diff_no_change() -> None:
    """変更なしの場合は空リストが返ることを確認。"""
    previous: list[dict] = [
        {"isrc": "US0000000001", "title": "Song A", "artist": "Artist A"},
    ]
    current = [
        Track(
            isrc="US0000000001",
            title="Song A",
            artist="Artist A",
            album="Album A",
        ),
    ]

    added, removed = compute_diff(previous, current)

    assert len(added) == 0
    assert len(removed) == 0


# ---------------------------------------------------------------------------
# resolve_conflicts
# ---------------------------------------------------------------------------


def test_resolve_conflicts_add_wins_by_timestamp() -> None:
    """追加の方が新しいタイムスタンプなら追加が採用されることを確認。"""
    track_added = Track(
        isrc="US0000000001",
        title="Song A",
        artist="Artist A",
        album="Album A",
        added_at="2025-06-02T00:00:00+00:00",
    )
    track_removed = {
        "isrc": "US0000000001",
        "title": "Song A",
        "artist": "Artist A",
        "added_at": "2025-06-01T00:00:00+00:00",
    }

    diffs_by_service = {
        "spotify": ([track_added], []),
        "apple_music": ([], [track_removed]),
    }

    to_add, to_remove = resolve_conflicts(diffs_by_service)

    assert len(to_add) == 1
    assert to_add[0].isrc == "US0000000001"
    assert len(to_remove) == 0


def test_resolve_conflicts_remove_wins_by_timestamp() -> None:
    """削除の方が新しいタイムスタンプなら削除が採用されることを確認。"""
    track_added = Track(
        isrc="US0000000001",
        title="Song A",
        artist="Artist A",
        album="Album A",
        added_at="2025-06-01T00:00:00+00:00",
    )
    track_removed = {
        "isrc": "US0000000001",
        "title": "Song A",
        "artist": "Artist A",
        "added_at": "2025-06-02T00:00:00+00:00",
    }

    diffs_by_service = {
        "spotify": ([track_added], []),
        "apple_music": ([], [track_removed]),
    }

    to_add, to_remove = resolve_conflicts(diffs_by_service)

    assert len(to_add) == 0
    assert len(to_remove) == 1


def test_resolve_conflicts_no_timestamp_add_wins() -> None:
    """タイムスタンプなしの場合は追加優先であることを確認。"""
    track_added = Track(
        isrc="US0000000001",
        title="Song A",
        artist="Artist A",
        album="Album A",
        added_at=None,
    )
    track_removed = {
        "isrc": "US0000000001",
        "title": "Song A",
        "artist": "Artist A",
    }

    diffs_by_service = {
        "spotify": ([track_added], []),
        "apple_music": ([], [track_removed]),
    }

    to_add, to_remove = resolve_conflicts(diffs_by_service)

    assert len(to_add) == 1
    assert to_add[0].isrc == "US0000000001"
    assert len(to_remove) == 0
