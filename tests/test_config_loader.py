from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.config_loader import load_config, load_playlists
from src.models import PlaylistConfig, SyncConfig


class TestLoadPlaylists:
    """load_playlists 関数のテストスイート。"""

    def test_load_playlists_success(self, tmp_path: Path) -> None:
        """有効なYAMLファイルから PlaylistConfig のリストが正しく返されることを確認。"""
        config_data = {
            "playlists": [
                {
                    "name": "Favorites 2025",
                    "spotify": {"playlist_id": "37i9dQZF1DXcBWIGoYBM5M"},
                    "apple_music": {
                        "playlist_url": "https://music.apple.com/jp/playlist/favorites-2025/pl.example1"
                    },
                    "amazon_music": {
                        "playlist_url": "https://music.amazon.co.jp/user-playlists/example1"
                    },
                },
                {
                    "name": "Workout Mix",
                    "spotify": {"playlist_id": "5ABHKGoOzxkaa28ttQV9sE"},
                    "apple_music": {
                        "playlist_url": "https://music.apple.com/jp/playlist/workout-mix/pl.example2"
                    },
                    "amazon_music": {
                        "playlist_url": "https://music.amazon.co.jp/user-playlists/example2"
                    },
                },
            ]
        }

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        result = load_playlists(config_file)

        assert len(result) == 2
        assert all(isinstance(p, PlaylistConfig) for p in result)

        # 1件目の検証
        assert result[0].name == "Favorites 2025"
        assert result[0].spotify == {"playlist_id": "37i9dQZF1DXcBWIGoYBM5M"}
        assert result[0].apple_music == {
            "playlist_url": "https://music.apple.com/jp/playlist/favorites-2025/pl.example1"
        }
        assert result[0].amazon_music == {
            "playlist_url": "https://music.amazon.co.jp/user-playlists/example1"
        }

        # 2件目の検証
        assert result[1].name == "Workout Mix"
        assert result[1].spotify == {"playlist_id": "5ABHKGoOzxkaa28ttQV9sE"}
        assert result[1].apple_music == {
            "playlist_url": "https://music.apple.com/jp/playlist/workout-mix/pl.example2"
        }
        assert result[1].amazon_music == {
            "playlist_url": "https://music.amazon.co.jp/user-playlists/example2"
        }

    def test_load_playlists_file_not_found(self) -> None:
        """存在しないパスを指定した場合に FileNotFoundError が発生することを確認。"""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_playlists("/nonexistent/path/playlists.yaml")

    def test_load_playlists_missing_playlists_key(self, tmp_path: Path) -> None:
        """playlists キーのないYAMLで ValueError が発生することを確認。"""
        config_data = {"notification": {"email": "user@example.com"}}

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        with pytest.raises(ValueError, match="Config file must contain 'playlists' key"):
            load_playlists(config_file)

    def test_load_playlists_missing_name(self, tmp_path: Path) -> None:
        """name フィールドのないエントリで ValueError が発生することを確認。"""
        config_data = {
            "playlists": [
                {
                    "spotify": {"playlist_id": "37i9dQZF1DXcBWIGoYBM5M"},
                }
            ]
        }

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        with pytest.raises(ValueError, match="Playlist entry missing required 'name' field"):
            load_playlists(config_file)

    def test_load_playlists_duplicate_name(self, tmp_path: Path) -> None:
        """同じ名前のプレイリストが重複した場合に ValueError が発生することを確認。"""
        config_data = {
            "playlists": [
                {"name": "Favorites 2025", "spotify": {"playlist_id": "id1"}},
                {"name": "Favorites 2025", "spotify": {"playlist_id": "id2"}},
            ]
        }

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        with pytest.raises(ValueError, match="Duplicate playlist name"):
            load_playlists(config_file)


class TestLoadConfig:
    """load_config 関数のテストスイート。"""

    def test_load_config_with_auto_discover(self, tmp_path: Path) -> None:
        """auto_discover: true を含む設定を正しく読み込む。"""
        config_data = {
            "auto_discover": True,
            "playlists": [
                {"name": "Test", "spotify": {"playlist_id": "sp1"}},
            ],
        }

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        result = load_config(config_file)

        assert isinstance(result, SyncConfig)
        assert result.auto_discover is True
        assert len(result.playlists) == 1
        assert result.playlists[0].name == "Test"

    def test_load_config_without_auto_discover(self, tmp_path: Path) -> None:
        """auto_discover が未設定の場合は False になる。"""
        config_data = {
            "playlists": [
                {"name": "Test", "spotify": {"playlist_id": "sp1"}},
            ],
        }

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        result = load_config(config_file)

        assert result.auto_discover is False
        assert len(result.playlists) == 1

    def test_load_config_without_playlists(self, tmp_path: Path) -> None:
        """playlists キーがない場合は空リスト。"""
        config_data = {"auto_discover": True}

        config_file = tmp_path / "playlists.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True)

        result = load_config(config_file)

        assert result.auto_discover is True
        assert result.playlists == []

    def test_load_config_file_not_found(self) -> None:
        """存在しないパスで FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path.yaml")

    def test_load_config_empty_file(self, tmp_path: Path) -> None:
        """空ファイルで ValueError。"""
        config_file = tmp_path / "playlists.yaml"
        config_file.write_text("")

        with pytest.raises(ValueError, match="Config file is empty"):
            load_config(config_file)
