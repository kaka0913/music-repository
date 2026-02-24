from __future__ import annotations

from pathlib import Path

import yaml

_selectors: dict | None = None


def load_selectors(config_path: str | Path = "config/selectors.yaml") -> dict:
    """セレクタ定義ファイルを読み込む。キャッシュあり。"""
    global _selectors
    if _selectors is not None:
        return _selectors

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Selectors config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        _selectors = yaml.safe_load(f)

    return _selectors


def get_selectors(service: str) -> dict:
    """指定サービスのセレクタ辞書を返す。"""
    selectors = load_selectors()
    if service not in selectors:
        raise KeyError(f"No selectors defined for service: {service}")
    return selectors[service]
