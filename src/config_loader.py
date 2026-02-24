from __future__ import annotations

from pathlib import Path

import yaml

from src.models import PlaylistConfig, SyncConfig


def load_playlists(config_path: str | Path = "config/playlists.yaml") -> list[PlaylistConfig]:
    """playlists.yaml を読み込み、PlaylistConfig のリストを返す。"""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "playlists" not in data:
        raise ValueError("Config file must contain 'playlists' key")

    playlists = []
    names_seen: set[str] = set()

    for entry in data["playlists"]:
        if "name" not in entry:
            raise ValueError(f"Playlist entry missing required 'name' field: {entry}")

        name = entry["name"]
        if name in names_seen:
            raise ValueError(f"Duplicate playlist name: {name}")
        names_seen.add(name)

        playlists.append(
            PlaylistConfig(
                name=name,
                spotify=entry.get("spotify"),
                apple_music=entry.get("apple_music"),
                amazon_music=entry.get("amazon_music"),
            )
        )

    return playlists


def load_config(config_path: str | Path = "config/playlists.yaml") -> SyncConfig:
    """playlists.yaml を読み込み、SyncConfig を返す。"""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError("Config file is empty")

    auto_discover = bool(data.get("auto_discover", False))
    playlists = load_playlists(config_path) if "playlists" in data else []

    return SyncConfig(auto_discover=auto_discover, playlists=playlists)
