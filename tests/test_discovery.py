from __future__ import annotations

from unittest.mock import MagicMock

from src.discovery import (
    collect_all_playlists,
    create_missing_playlists,
    discover_and_merge_playlists,
    match_playlists_by_name,
    merge_with_manual,
    normalize_name,
)
from src.models import PlaylistConfig, PlaylistInfo


class TestNormalizeName:
    """normalize_name() のテスト。"""

    def test_basic(self) -> None:
        assert normalize_name("My Playlist") == "my playlist"

    def test_nfkc_normalization(self) -> None:
        # 全角英数字 → 半角
        assert normalize_name("Ｍｙ Ｐｌａｙｌｉｓｔ") == "my playlist"

    def test_strip_whitespace(self) -> None:
        assert normalize_name("  hello  ") == "hello"

    def test_japanese(self) -> None:
        assert normalize_name("お気に入り") == "お気に入り"

    def test_mixed(self) -> None:
        assert normalize_name("  Ｍｙ お気に入り  ") == "my お気に入り"


class TestCollectAllPlaylists:
    """collect_all_playlists() のテスト。"""

    def test_collects_from_all_providers(self) -> None:
        mock_spotify = MagicMock()
        mock_spotify.get_all_playlists.return_value = [("Rock", "sp1"), ("Jazz", "sp2")]

        mock_apple = MagicMock()
        mock_apple.get_all_playlists.return_value = [("Rock", "am1")]

        providers = {"spotify": mock_spotify, "apple_music": mock_apple}
        result = collect_all_playlists(providers)

        assert result["spotify"] == [("Rock", "sp1"), ("Jazz", "sp2")]
        assert result["apple_music"] == [("Rock", "am1")]

    def test_handles_provider_error(self) -> None:
        mock_spotify = MagicMock()
        mock_spotify.get_all_playlists.side_effect = Exception("API error")

        result = collect_all_playlists({"spotify": mock_spotify})

        assert result["spotify"] == []


class TestMatchPlaylistsByName:
    """match_playlists_by_name() のテスト。"""

    def test_matches_same_name_across_services(self) -> None:
        all_playlists = {
            "spotify": [("Rock", "sp1"), ("Jazz", "sp2")],
            "apple_music": [("Rock", "am1"), ("Pop", "am2")],
        }

        result = match_playlists_by_name(all_playlists)

        names = {info.name for info in result}
        assert names == {"Rock", "Jazz", "Pop"}

        rock = next(i for i in result if normalize_name(i.name) == "rock")
        assert rock.service_ids == {"spotify": "sp1", "apple_music": "am1"}

    def test_case_insensitive_match(self) -> None:
        all_playlists = {
            "spotify": [("My Playlist", "sp1")],
            "apple_music": [("my playlist", "am1")],
        }

        result = match_playlists_by_name(all_playlists)

        assert len(result) == 1
        assert len(result[0].service_ids) == 2

    def test_nfkc_match(self) -> None:
        """全角・半角の違いでもマッチする。"""
        all_playlists = {
            "spotify": [("Rock", "sp1")],
            "apple_music": [("Ｒｏｃｋ", "am1")],
        }

        result = match_playlists_by_name(all_playlists)

        assert len(result) == 1
        assert result[0].service_ids == {"spotify": "sp1", "apple_music": "am1"}

    def test_empty_input(self) -> None:
        result = match_playlists_by_name({})
        assert result == []


class TestCreateMissingPlaylists:
    """create_missing_playlists() のテスト。"""

    def test_creates_on_missing_service(self) -> None:
        matched = [
            PlaylistInfo(name="Rock", service_ids={"spotify": "sp1"}),
        ]

        mock_apple = MagicMock()
        mock_apple.create_playlist.return_value = "am_new"

        providers = {"spotify": MagicMock(), "apple_music": mock_apple}
        result = create_missing_playlists(matched, providers)

        mock_apple.create_playlist.assert_called_once_with("Rock")
        assert result[0].service_ids == {"spotify": "sp1", "apple_music": "am_new"}

    def test_no_creation_when_all_present(self) -> None:
        matched = [
            PlaylistInfo(name="Rock", service_ids={"spotify": "sp1", "apple_music": "am1"}),
        ]

        mock_spotify = MagicMock()
        mock_apple = MagicMock()

        providers = {"spotify": mock_spotify, "apple_music": mock_apple}
        create_missing_playlists(matched, providers)

        mock_spotify.create_playlist.assert_not_called()
        mock_apple.create_playlist.assert_not_called()

    def test_handles_creation_error(self) -> None:
        matched = [
            PlaylistInfo(name="Rock", service_ids={"spotify": "sp1"}),
        ]

        mock_apple = MagicMock()
        mock_apple.create_playlist.side_effect = Exception("Browser error")

        providers = {"spotify": MagicMock(), "apple_music": mock_apple}
        result = create_missing_playlists(matched, providers)

        # エラーがあっても既存のIDは保持
        assert result[0].service_ids == {"spotify": "sp1"}


class TestMergeWithManual:
    """merge_with_manual() のテスト。"""

    def test_manual_takes_priority(self) -> None:
        discovered = [
            PlaylistInfo(name="Rock", service_ids={"spotify": "sp_discovered", "apple_music": "am1"}),
        ]
        manual = [
            PlaylistConfig(name="Rock", spotify={"playlist_id": "sp_manual"}, apple_music=None, amazon_music=None),
        ]

        result = merge_with_manual(discovered, manual)

        assert len(result) == 1
        assert result[0].spotify == {"playlist_id": "sp_manual"}
        # 手動設定にない apple_music は発見したもので補完
        assert result[0].apple_music == {"playlist_url": "am1"}

    def test_discovery_only_playlist(self) -> None:
        discovered = [
            PlaylistInfo(name="Jazz", service_ids={"spotify": "sp1"}),
        ]
        manual: list[PlaylistConfig] = []

        result = merge_with_manual(discovered, manual)

        assert len(result) == 1
        assert result[0].name == "Jazz"
        assert result[0].spotify == {"playlist_id": "sp1"}

    def test_manual_only_playlist(self) -> None:
        discovered: list[PlaylistInfo] = []
        manual = [
            PlaylistConfig(name="Custom", spotify={"playlist_id": "sp1"}, apple_music=None, amazon_music=None),
        ]

        result = merge_with_manual(discovered, manual)

        assert len(result) == 1
        assert result[0].name == "Custom"

    def test_mixed(self) -> None:
        discovered = [
            PlaylistInfo(name="Rock", service_ids={"spotify": "sp1", "apple_music": "am1"}),
            PlaylistInfo(name="Jazz", service_ids={"apple_music": "am2"}),
        ]
        manual = [
            PlaylistConfig(name="Rock", spotify={"playlist_id": "sp_manual"}, apple_music=None, amazon_music=None),
            PlaylistConfig(name="Custom", spotify={"playlist_id": "sp_custom"}, apple_music=None, amazon_music=None),
        ]

        result = merge_with_manual(discovered, manual)

        names = {p.name for p in result}
        assert names == {"Rock", "Jazz", "Custom"}


class TestDiscoverAndMergePlaylists:
    """discover_and_merge_playlists() のテスト。"""

    def test_full_pipeline(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.discovery.CACHE_FILE", tmp_path / "cache.json")

        mock_spotify = MagicMock()
        mock_spotify.get_all_playlists.return_value = [("Rock", "sp1"), ("Jazz", "sp2")]

        mock_apple = MagicMock()
        mock_apple.get_all_playlists.return_value = [("Rock", "am1")]
        mock_apple.create_playlist.return_value = "am_jazz"

        providers = {"spotify": mock_spotify, "apple_music": mock_apple}
        manual = [
            PlaylistConfig(name="Rock", spotify={"playlist_id": "sp_override"}, apple_music=None, amazon_music=None),
        ]

        result = discover_and_merge_playlists(providers, manual)

        assert len(result) == 2
        rock = next(p for p in result if p.name == "Rock")
        assert rock.spotify == {"playlist_id": "sp_override"}
        assert rock.apple_music == {"playlist_url": "am1"}

        jazz = next(p for p in result if p.name == "Jazz")
        assert jazz.spotify == {"playlist_id": "sp2"}
        assert jazz.apple_music == {"playlist_url": "am_jazz"}

        # Jazz は Apple Music に存在しなかったため作成
        mock_apple.create_playlist.assert_called_once_with("Jazz")
