"""統合テスト: 全プロバイダーをモックした sync_playlist / main のテスト。

pytest + unittest.mock を使用。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import PlaylistConfig, SyncConfig, SyncResult, Track
from src.providers.base import MusicProvider
from src.sync_engine import sync_playlist


# ---------------------------------------------------------------------------
# Helper: プレイリスト設定とプロバイダーのセットアップ
# ---------------------------------------------------------------------------

def _make_playlist_config() -> PlaylistConfig:
    """テスト用の3サービス構成のプレイリスト設定を返す。"""
    return PlaylistConfig(
        name="test_playlist",
        spotify={"playlist_id": "sp_123"},
        apple_music={"playlist_url": "am_456"},
        amazon_music={"playlist_url": "az_789"},
    )


def _make_providers() -> dict[str, MagicMock]:
    """3サービス分のモックプロバイダーを返す。"""
    return {
        "spotify": MagicMock(spec=MusicProvider),
        "apple_music": MagicMock(spec=MusicProvider),
        "amazon_music": MagicMock(spec=MusicProvider),
    }


# ---------------------------------------------------------------------------
# 共通トラックデータ
# ---------------------------------------------------------------------------

TRACK_A = Track(
    isrc="US0000000001",
    title="Song A",
    artist="Artist A",
    album="Album A",
    service_ids={"spotify": "sp_a"},
    added_at="2025-06-01T00:00:00+00:00",
)

TRACK_B = Track(
    isrc="US0000000002",
    title="Song B",
    artist="Artist B",
    album="Album B",
    service_ids={"spotify": "sp_b"},
    added_at="2025-06-02T00:00:00+00:00",
)

TRACK_C = Track(
    isrc="US0000000003",
    title="Song C",
    artist="Artist C",
    album="Album C",
    service_ids={"apple_music": "am_c"},
    added_at="2025-06-03T00:00:00+00:00",
)


# ===========================================================================
# 1. test_sync_playlist_full_flow
# ===========================================================================


class TestSyncPlaylistFullFlow:
    """3サービスをモックして sync_playlist のフルフローを検証する。"""

    def test_sync_playlist_full_flow(self, tmp_path: Path) -> None:
        """Spotify にあるが Apple Music にない曲が Apple Music への追加対象になること、
        SyncResult の added / errors が適切に設定されること、
        state ファイルが保存されることを確認する。
        """
        config = _make_playlist_config()
        providers = _make_providers()

        # 前回状態: Song A のみ存在（ベースライン）
        # → Song B は Spotify に新たに追加された扱いになる
        previous_state = {
            "playlist_name": "test_playlist",
            "last_synced_at": "2025-06-01T00:00:00+00:00",
            "tracks": [
                {
                    "isrc": "US0000000001",
                    "title": "Song A",
                    "artist": "Artist A",
                    "album": "Album A",
                    "service_ids": {"spotify": "sp_a", "apple_music": "am_a", "amazon_music": "az_a"},
                    "added_at": "2025-06-01T00:00:00+00:00",
                },
            ],
            "unmatched": [],
        }
        state_file = tmp_path / "test_playlist.json"
        state_file.write_text(
            json.dumps(previous_state, ensure_ascii=False), encoding="utf-8"
        )

        # Spotify: A, B を保持
        providers["spotify"].get_playlist_tracks.return_value = [TRACK_A, TRACK_B]
        # Apple Music: A のみ保持 (B が不足)
        providers["apple_music"].get_playlist_tracks.return_value = [TRACK_A]
        # Amazon Music: A のみ保持 (B が不足)
        providers["amazon_music"].get_playlist_tracks.return_value = [TRACK_A]

        # find_match: ISRC が一致する Track を返す (追加対象の楽曲を見つけたことにする)
        matched_b_apple = Track(
            isrc="US0000000002",
            title="Song B",
            artist="Artist B",
            album="Album B",
            service_ids={"apple_music": "am_b"},
        )
        matched_b_amazon = Track(
            isrc="US0000000002",
            title="Song B",
            artist="Artist B",
            album="Album B",
            service_ids={"amazon_music": "az_b"},
        )

        def fake_find_match(track, provider, playlist_id=""):
            """サービスごとに適切なマッチ結果を返す。"""
            if provider is providers["apple_music"]:
                return matched_b_apple
            if provider is providers["amazon_music"]:
                return matched_b_amazon
            return None

        with (
            patch("src.sync_engine.STATE_DIR", tmp_path),
            patch("src.sync_engine.find_match", side_effect=fake_find_match),
        ):
            result = sync_playlist(config, providers)

        # --- アサーション ---
        # Apple Music と Amazon Music に Song B が追加されること
        assert len(result.added) >= 1
        added_isrcs = [t.isrc for t in result.added]
        assert "US0000000002" in added_isrcs

        # Apple Music の add_tracks が呼ばれること
        providers["apple_music"].add_tracks.assert_called_once()
        call_args = providers["apple_music"].add_tracks.call_args
        assert call_args[0][0] == "am_456"  # playlist_id
        add_isrcs = [t.isrc for t in call_args[0][1]]
        assert "US0000000002" in add_isrcs

        # Amazon Music の add_tracks が呼ばれること
        providers["amazon_music"].add_tracks.assert_called_once()

        # errors は空
        assert result.errors == []

        # state ファイルが生成されること
        state_file = tmp_path / "test_playlist.json"
        assert state_file.exists()

        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved["last_synced_at"] is not None
        # 全サービスのトラックがマージされている
        saved_isrcs = {t["isrc"] for t in saved["tracks"]}
        assert "US0000000001" in saved_isrcs
        assert "US0000000002" in saved_isrcs


# ===========================================================================
# 2. test_sync_playlist_with_conflict
# ===========================================================================


class TestSyncPlaylistWithConflict:
    """追加と削除が競合するケースの検証。"""

    def test_sync_playlist_with_conflict(self, tmp_path: Path) -> None:
        """サービスAで追加された ISRC がサービスBで削除されている場合、
        タイムスタンプに基づいて適切に解決されることを確認する。
        """
        config = _make_playlist_config()
        providers = _make_providers()

        # 前回状態: Song X が存在していた
        previous_state = {
            "playlist_name": "test_playlist",
            "last_synced_at": "2025-06-01T00:00:00+00:00",
            "tracks": [
                {
                    "isrc": "US0000000099",
                    "title": "Song X",
                    "artist": "Artist X",
                    "album": "Album X",
                    "service_ids": {"spotify": "sp_x", "apple_music": "am_x"},
                    "added_at": "2025-05-01T00:00:00+00:00",
                },
            ],
            "unmatched": [],
        }
        state_file = tmp_path / "test_playlist.json"
        state_file.write_text(
            json.dumps(previous_state, ensure_ascii=False), encoding="utf-8"
        )

        # Spotify: Song X を保持 + 新たに Song Y を追加 (added_at が新しい)
        track_x_sp = Track(
            isrc="US0000000099",
            title="Song X",
            artist="Artist X",
            album="Album X",
            service_ids={"spotify": "sp_x"},
            added_at="2025-05-01T00:00:00+00:00",
        )
        track_y = Track(
            isrc="US0000000088",
            title="Song Y",
            artist="Artist Y",
            album="Album Y",
            service_ids={"spotify": "sp_y"},
            added_at="2025-06-10T00:00:00+00:00",
        )
        providers["spotify"].get_playlist_tracks.return_value = [track_x_sp, track_y]

        # Apple Music: Song X を削除した (リストに存在しない)
        # → compute_diff で Song X は removed に入る
        providers["apple_music"].get_playlist_tracks.return_value = []

        # Amazon Music: Song X のみ残っている
        track_x_az = Track(
            isrc="US0000000099",
            title="Song X",
            artist="Artist X",
            album="Album X",
            service_ids={"amazon_music": "az_x"},
            added_at="2025-05-01T00:00:00+00:00",
        )
        providers["amazon_music"].get_playlist_tracks.return_value = [track_x_az]

        # find_match: Song Y を各サービスで見つけたことにする
        matched_y_apple = Track(
            isrc="US0000000088",
            title="Song Y",
            artist="Artist Y",
            album="Album Y",
            service_ids={"apple_music": "am_y"},
        )
        matched_y_amazon = Track(
            isrc="US0000000088",
            title="Song Y",
            artist="Artist Y",
            album="Album Y",
            service_ids={"amazon_music": "az_y"},
        )

        def fake_find_match(track, provider, playlist_id=""):
            if track.isrc == "US0000000088":
                if provider is providers["apple_music"]:
                    return matched_y_apple
                if provider is providers["amazon_music"]:
                    return matched_y_amazon
            return None

        with (
            patch("src.sync_engine.STATE_DIR", tmp_path),
            patch("src.sync_engine.find_match", side_effect=fake_find_match),
        ):
            result = sync_playlist(config, providers)

        # Song Y (added_at=06-10) は Spotify での追加が最新 → 追加として採用される
        added_isrcs = [t.isrc for t in result.added]
        assert "US0000000088" in added_isrcs

        # エラーは発生しない
        assert result.errors == []


# ===========================================================================
# 3. test_sync_playlist_unmatched
# ===========================================================================


class TestSyncPlaylistUnmatched:
    """find_match が None を返す場合に unmatched に記録されることの検証。"""

    def test_sync_playlist_unmatched(self, tmp_path: Path) -> None:
        """find_match が None を返す場合、unmatched リストに楽曲情報が記録されることを確認する。"""
        config = _make_playlist_config()
        providers = _make_providers()

        # 前回状態: Song A のみ存在（ベースライン）
        previous_state = {
            "playlist_name": "test_playlist",
            "last_synced_at": "2025-06-01T00:00:00+00:00",
            "tracks": [
                {
                    "isrc": "US0000000001",
                    "title": "Song A",
                    "artist": "Artist A",
                    "album": "Album A",
                    "service_ids": {"spotify": "sp_a", "apple_music": "am_a", "amazon_music": "az_a"},
                    "added_at": "2025-06-01T00:00:00+00:00",
                },
            ],
            "unmatched": [],
        }
        state_file = tmp_path / "test_playlist.json"
        state_file.write_text(
            json.dumps(previous_state, ensure_ascii=False), encoding="utf-8"
        )

        # Spotify: Song A, Song B を保持
        providers["spotify"].get_playlist_tracks.return_value = [TRACK_A, TRACK_B]
        # Apple Music: Song A のみ (Song B が不足)
        providers["apple_music"].get_playlist_tracks.return_value = [TRACK_A]
        # Amazon Music: Song A のみ (Song B が不足)
        providers["amazon_music"].get_playlist_tracks.return_value = [TRACK_A]

        # find_match は常に None を返す (マッチが見つからない)
        with (
            patch("src.sync_engine.STATE_DIR", tmp_path),
            patch("src.sync_engine.find_match", return_value=None),
        ):
            result = sync_playlist(config, providers)

        # 追加は行われない (マッチが見つからないため)
        assert len(result.added) == 0

        # unmatched に Song B の情報が記録されること
        assert len(result.unmatched) >= 1
        unmatched_isrcs = [u["isrc"] for u in result.unmatched]
        assert "US0000000002" in unmatched_isrcs

        # unmatched エントリに必要な情報が含まれていること
        entry = next(u for u in result.unmatched if u["isrc"] == "US0000000002")
        assert entry["title"] == "Song B"
        assert entry["artist"] == "Artist B"
        assert "reason" in entry
        assert "detected_at" in entry


# ===========================================================================
# 4. test_sync_playlist_provider_error
# ===========================================================================


class TestSyncPlaylistProviderError:
    """get_playlist_tracks が例外を投げた場合の検証。"""

    def test_sync_playlist_provider_error(self, tmp_path: Path) -> None:
        """1サービスが例外を投げても、他サービスの同期は続行され、
        エラーが SyncResult.errors に記録されることを確認する。
        """
        config = _make_playlist_config()
        providers = _make_providers()

        # Spotify: 例外を送出
        providers["spotify"].get_playlist_tracks.side_effect = ConnectionError(
            "Spotify API timeout"
        )
        # Apple Music: 正常に Song A を返す
        providers["apple_music"].get_playlist_tracks.return_value = [TRACK_A]
        # Amazon Music: 正常に Song A を返す
        providers["amazon_music"].get_playlist_tracks.return_value = [TRACK_A]

        with (
            patch("src.sync_engine.STATE_DIR", tmp_path),
            patch("src.sync_engine.find_match", return_value=None),
        ):
            result = sync_playlist(config, providers)

        # Spotify のエラーが errors に記録されていること
        assert len(result.errors) >= 1
        spotify_errors = [e for e in result.errors if "spotify" in e.lower()]
        assert len(spotify_errors) >= 1
        assert "Spotify API timeout" in spotify_errors[0]

        # 他のサービスの処理は続行される (state ファイルが保存される)
        state_file = tmp_path / "test_playlist.json"
        assert state_file.exists()

    def test_sync_playlist_all_providers_fail(self, tmp_path: Path) -> None:
        """全サービスが失敗した場合、適切なエラーが返ること。"""
        config = _make_playlist_config()
        providers = _make_providers()

        providers["spotify"].get_playlist_tracks.side_effect = ConnectionError("fail")
        providers["apple_music"].get_playlist_tracks.side_effect = ConnectionError(
            "fail"
        )
        providers["amazon_music"].get_playlist_tracks.side_effect = ConnectionError(
            "fail"
        )

        with patch("src.sync_engine.STATE_DIR", tmp_path):
            result = sync_playlist(config, providers)

        # 全サービス失敗 → "No tracks retrieved from any service" エラー
        assert any(
            "No tracks retrieved" in e for e in result.errors
        )


# ===========================================================================
# 5. test_main_orchestration
# ===========================================================================


class TestMainOrchestration:
    """main() 関数のオーケストレーションテスト。"""

    def test_main_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """正常終了時に return 0 を確認する。"""
        from src.main import main

        mock_playlists = [
            PlaylistConfig(
                name="pl1",
                spotify={"playlist_id": "sp_1"},
            )
        ]
        mock_config = SyncConfig(auto_discover=False, playlists=mock_playlists)
        mock_result = SyncResult(added=[], removed=[], unmatched=[], errors=[])

        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
        monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        mock_provider = MagicMock(spec=MusicProvider)

        with (
            patch("src.main.load_config", return_value=mock_config) as m_load,
            patch(
                "src.main.init_providers",
                return_value={"spotify": mock_provider},
            ) as m_init,
            patch(
                "src.main.sync_playlist", return_value=mock_result
            ) as m_sync,
            patch("src.main.notify_if_needed") as m_notify,
        ):
            exit_code = main()

        assert exit_code == 0
        m_load.assert_called_once()
        m_init.assert_called_once()
        m_sync.assert_called_once()
        # 通知環境変数がないため notify_if_needed は呼ばれない
        m_notify.assert_not_called()

    def test_main_with_errors_returns_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同期結果にエラーが含まれる場合に return 1 を確認する。"""
        from src.main import main

        mock_playlists = [
            PlaylistConfig(
                name="pl1",
                spotify={"playlist_id": "sp_1"},
            )
        ]
        mock_config = SyncConfig(auto_discover=False, playlists=mock_playlists)
        mock_result = SyncResult(
            added=[],
            removed=[],
            unmatched=[],
            errors=["spotify: Failed to get tracks - timeout"],
        )

        monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        mock_provider = MagicMock(spec=MusicProvider)

        with (
            patch("src.main.load_config", return_value=mock_config),
            patch(
                "src.main.init_providers",
                return_value={"spotify": mock_provider},
            ),
            patch("src.main.sync_playlist", return_value=mock_result),
            patch("src.main.notify_if_needed"),
        ):
            exit_code = main()

        assert exit_code == 1

    def test_main_load_config_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """設定読み込みに失敗した場合に return 1 を確認する。"""
        from src.main import main

        monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        with patch(
            "src.main.load_config",
            side_effect=FileNotFoundError("config not found"),
        ):
            exit_code = main()

        assert exit_code == 1

    def test_main_no_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """プロバイダーが1つも初期化できなかった場合に return 1 を確認する。"""
        from src.main import main

        mock_playlists = [
            PlaylistConfig(name="pl1", spotify={"playlist_id": "sp_1"})
        ]
        mock_config = SyncConfig(auto_discover=False, playlists=mock_playlists)

        monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        with (
            patch("src.main.load_config", return_value=mock_config),
            patch("src.main.init_providers", return_value={}),
        ):
            exit_code = main()

        assert exit_code == 1

    def test_main_with_notification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """通知環境変数が設定されている場合に notify_if_needed が呼ばれることを確認する。"""
        from src.main import main

        mock_playlists = [
            PlaylistConfig(name="pl1", spotify={"playlist_id": "sp_1"})
        ]
        mock_config = SyncConfig(auto_discover=False, playlists=mock_playlists)
        mock_result = SyncResult(
            added=[],
            removed=[],
            unmatched=[{"title": "X", "artist": "Y", "reason": "not found"}],
            errors=[],
        )

        monkeypatch.setenv("NOTIFICATION_EMAIL", "test@example.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "app_pass")

        mock_provider = MagicMock(spec=MusicProvider)

        with (
            patch("src.main.load_config", return_value=mock_config),
            patch(
                "src.main.init_providers",
                return_value={"spotify": mock_provider},
            ),
            patch("src.main.sync_playlist", return_value=mock_result),
            patch("src.main.notify_if_needed") as m_notify,
        ):
            exit_code = main()

        # unmatched があっても SyncResult.errors が空なら return 0
        assert exit_code == 0
        m_notify.assert_called_once()
        # 引数の確認
        call_args = m_notify.call_args
        assert call_args[0][1] == "test@example.com"
        assert call_args[0][2] == "app_pass"
