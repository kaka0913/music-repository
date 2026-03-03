#!/usr/bin/env python3
"""CSS セレクタ検証ツール (Phase 6.1)。

config/selectors.yaml に定義されたセレクタが実際のウェブサイトで
有効かどうかを Playwright で検証する。

Usage:
    python tools/verify_selectors.py --service apple_music
    python tools/verify_selectors.py --service amazon_music --no-headless
    python tools/verify_selectors.py --service all --suggest
    python tools/verify_selectors.py --service apple_music --playlist-url "https://music.apple.com/..."
    python -m tools.verify_selectors --service all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# プロジェクトルートを sys.path に追加 (直接実行時に必要)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.providers.playwright_helper import browser_context, load_cookies_from_secret
from src.providers.selector_loader import get_selectors

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVICE_SECRET_MAP: dict[str, str] = {
    "apple_music": "apple-music-cookie",
    "amazon_music": "amazon-music-cookie",
}

# ページ種別ごとのセレクタグループ定義
SELECTOR_GROUPS: dict[str, dict[str, list[str]]] = {
    "apple_music": {
        "library": [
            "library_playlist_row",
            "library_playlist_name",
            "library_playlist_link",
            # new_playlist_button: Apple Music Web はプレイリスト作成非対応のため検証対象外
        ],
        "playlist": [
            "playlist_track_row",
            "track_title",
            "track_artist",
        ],
        "search": [
            "search_input",
        ],
        "auth": [
            "logged_in_indicator",
        ],
    },
    "amazon_music": {
        "library": [
            "library_playlist_row",
            "library_playlist_name",
            "library_playlist_link",
            "new_playlist_button",
        ],
        "playlist": [
            "playlist_track_row",
            "track_title",
            "track_artist",
        ],
        "search": [
            "search_input",
        ],
        "auth": [
            "logged_in_indicator",
        ],
    },
}

# 各ページタイプのナビゲーション先 URL
PAGE_URLS: dict[str, dict[str, str]] = {
    "apple_music": {
        "library": "https://music.apple.com/library/playlists",
        "search": "https://music.apple.com/search",
    },
    "amazon_music": {
        "library": "https://music.amazon.co.jp/my/playlists",
        "search": "https://music.amazon.co.jp",
    },
}

# --suggest モード用: セレクタが見つからなかった場合に試す広範囲クエリ
SUGGEST_QUERIES: dict[str, list[str]] = {
    "library_playlist_row": [
        "[class*='playlist']",
        "[class*='grid'] li",
        "[class*='shelf'] li",
        "[class*='card']",
        "[data-testid*='playlist']",
        "a[href*='playlist']",
    ],
    "library_playlist_name": [
        "[class*='playlist'] [class*='title']",
        "[class*='playlist'] [class*='name']",
        "[class*='card'] [class*='title']",
        "[data-testid*='title']",
    ],
    "library_playlist_link": [
        "a[href*='playlist']",
        "a[href*='/pl/']",
    ],
    "new_playlist_button": [
        "button[class*='create']",
        "button[class*='new']",
        "[data-testid*='create']",
        "[data-testid*='new-playlist']",
        "[aria-label*='Create']",
        "[aria-label*='New']",
        "[aria-label*='作成']",
        "[aria-label*='新規']",
    ],
    "playlist_track_row": [
        "[class*='track']",
        "[class*='song']",
        "[class*='row']",
        "[data-testid*='track']",
        "tr[class*='track']",
    ],
    "track_title": [
        "[class*='song-name']",
        "[class*='track-title']",
        "[class*='trackTitle']",
        "[data-testid*='title']",
    ],
    "track_artist": [
        "[class*='artist']",
        "[class*='by-line']",
        "[class*='subtitle']",
        "[data-testid*='artist']",
    ],
    "search_input": [
        "input[type='search']",
        "input[placeholder*='Search']",
        "input[placeholder*='検索']",
        "input[aria-label*='Search']",
        "input[aria-label*='検索']",
        "#searchInput",
        "[data-testid*='search']",
    ],
    "logged_in_indicator": [
        "[data-testid*='user']",
        "[class*='user-menu']",
        "[class*='profile']",
        "[class*='account']",
        "#navbarMusicTitle",
        "nav [class*='user']",
    ],
    "new_playlist_name_input": [
        "input[placeholder*='Playlist']",
        "input[placeholder*='プレイリスト']",
        "input[type='text']",
        "[data-testid*='playlist-name']",
    ],
    "new_playlist_confirm": [
        "button[type='submit']",
        "[data-testid*='confirm']",
        "[data-testid*='create']",
        "button[class*='confirm']",
        "button[class*='create']",
    ],
    "search_result_row": [
        "[class*='search-result']",
        "[class*='searchResult']",
        "[data-testid*='search-result']",
    ],
    "add_to_playlist_button": [
        "[class*='add-to-playlist']",
        "[class*='addToPlaylist']",
        "[data-testid*='add-to-playlist']",
        "button[aria-label*='Add']",
        "button[aria-label*='追加']",
    ],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SelectorResult:
    """1 つのセレクタの検証結果。"""

    name: str
    css: str
    found: bool
    count: int = 0
    suggestions: list[str] = field(default_factory=list)


@dataclass
class PageResult:
    """1 ページ分の検証結果。"""

    page_type: str
    url: str
    selectors: list[SelectorResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ServiceResult:
    """1 サービス全体の検証結果。"""

    service: str
    pages: list[PageResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Core verification logic
# ---------------------------------------------------------------------------

async def _check_selector(
    page,
    name: str,
    css: str,
    suggest: bool = False,
) -> SelectorResult:
    """ページ上でセレクタを検証し、結果を返す。"""
    try:
        elements = await page.query_selector_all(css)
        count = len(elements)
        found = count > 0
    except Exception as exc:
        logger.debug("Selector '%s' (%s) raised an error: %s", name, css, exc)
        found = False
        count = 0

    suggestions: list[str] = []
    if not found and suggest:
        candidates = SUGGEST_QUERIES.get(name, [])
        for candidate_css in candidates:
            # 定義済みセレクタと同じなら飛ばす
            if candidate_css == css:
                continue
            try:
                elems = await page.query_selector_all(candidate_css)
                if elems:
                    suggestions.append(f"{candidate_css}  ({len(elems)} hit(s))")
            except Exception:
                pass

    return SelectorResult(
        name=name,
        css=css,
        found=found,
        count=count,
        suggestions=suggestions,
    )


async def _verify_page(
    page,
    url: str,
    page_type: str,
    selector_names: list[str],
    selectors: dict[str, str],
    suggest: bool = False,
    wait_after_nav: float = 3.0,
) -> PageResult:
    """指定 URL へ遷移し、セレクタ群を検証する。"""
    result = PageResult(page_type=page_type, url=url)

    try:
        await page.goto(url, wait_until="networkidle", timeout=60_000)
    except Exception as exc:
        logger.warning("Navigation to %s failed: %s", url, exc)
        # タイムアウトでも部分的にロードされている可能性があるので続行を試みる
        pass

    # ページが動的に読み込まれるのを少し待つ
    await asyncio.sleep(wait_after_nav)

    for sel_name in selector_names:
        css = selectors.get(sel_name)
        if css is None:
            # selectors.yaml に存在しない (login_url 等は CSS セレクタではない)
            continue
        sr = await _check_selector(page, sel_name, css, suggest=suggest)
        result.selectors.append(sr)

    return result


async def verify_service(
    service: str,
    headless: bool = True,
    playlist_url: str | None = None,
    suggest: bool = False,
    timeout: int = 60_000,
) -> ServiceResult:
    """1 サービスのセレクタを全て検証する。"""
    service_result = ServiceResult(service=service)

    # ─── Cookie 取得 ───
    secret_id = SERVICE_SECRET_MAP.get(service)
    if not secret_id:
        service_result.skipped = True
        service_result.skip_reason = f"Unknown service: {service}"
        return service_result

    try:
        cookies = load_cookies_from_secret(secret_id)
    except Exception as exc:
        service_result.skipped = True
        service_result.skip_reason = (
            f"Cookie 取得失敗 ({secret_id}): {exc}  -- このサービスはスキップします。"
        )
        return service_result

    # ─── セレクタ定義 ───
    try:
        selectors = get_selectors(service)
    except KeyError as exc:
        service_result.skipped = True
        service_result.skip_reason = f"セレクタ定義なし: {exc}"
        return service_result

    groups = SELECTOR_GROUPS.get(service, {})
    urls = PAGE_URLS.get(service, {})

    # ─── ブラウザを起動して各ページを検証 ───
    async with browser_context(cookies=cookies, headless=headless, timeout=timeout) as (_ctx, page):

        # --- Auth indicator (ライブラリページで確認) ---
        auth_selectors = groups.get("auth", [])
        library_url = urls.get("library", "")
        if auth_selectors and library_url:
            pr = await _verify_page(
                page,
                url=library_url,
                page_type="Auth (on Library page)",
                selector_names=auth_selectors,
                selectors=selectors,
                suggest=suggest,
            )
            service_result.pages.append(pr)

        # --- Library page ---
        library_selectors = groups.get("library", [])
        if library_selectors and library_url:
            # auth の確認で既にライブラリページにいるが、念のためリロード
            pr = await _verify_page(
                page,
                url=library_url,
                page_type="Library",
                selector_names=library_selectors,
                selectors=selectors,
                suggest=suggest,
            )
            service_result.pages.append(pr)

        # --- Playlist page (requires --playlist-url) ---
        playlist_selectors = groups.get("playlist", [])
        if playlist_selectors:
            if playlist_url:
                pr = await _verify_page(
                    page,
                    url=playlist_url,
                    page_type="Playlist",
                    selector_names=playlist_selectors,
                    selectors=selectors,
                    suggest=suggest,
                )
                service_result.pages.append(pr)
            else:
                pr = PageResult(
                    page_type="Playlist",
                    url="(not tested)",
                    skipped=True,
                    skip_reason="--playlist-url が未指定。プレイリストページのセレクタは検証をスキップしました。",
                )
                service_result.pages.append(pr)

        # --- Search page ---
        search_selectors = groups.get("search", [])
        search_url = urls.get("search", "")
        if search_selectors and search_url:
            pr = await _verify_page(
                page,
                url=search_url,
                page_type="Search",
                selector_names=search_selectors,
                selectors=selectors,
                suggest=suggest,
            )
            service_result.pages.append(pr)

    return service_result


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

# ANSI colors
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _truncate(text: str, max_len: int = 45) -> str:
    """長すぎるテキストを切り詰める。"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def render_report(results: Sequence[ServiceResult]) -> str:
    """検証結果を人間が読みやすいテキストレポートとして返す。"""
    lines: list[str] = []

    for sr in results:
        header = f"=== {sr.service} Selector Verification ==="
        lines.append("")
        lines.append(f"{_BOLD}{_CYAN}{header}{_RESET}")

        if sr.skipped:
            lines.append(f"  {_YELLOW}WARNING: {sr.skip_reason}{_RESET}")
            lines.append("")
            continue

        total = 0
        passed = 0

        for pr in sr.pages:
            lines.append(f"  {_BOLD}Page: {pr.page_type}{_RESET} ({pr.url})")

            if pr.skipped:
                lines.append(f"    {_YELLOW}SKIPPED: {pr.skip_reason}{_RESET}")
                lines.append("")
                continue

            for sel_r in pr.selectors:
                total += 1
                css_display = _truncate(sel_r.css)
                if sel_r.found:
                    passed += 1
                    mark = f"{_GREEN}OK{_RESET}"
                    count_str = f"(found: {sel_r.count} element(s))"
                    lines.append(
                        f"    {mark}  {sel_r.name:<30s} {css_display:<48s} {count_str}"
                    )
                else:
                    mark = f"{_RED}NG{_RESET}"
                    lines.append(
                        f"    {mark}  {sel_r.name:<30s} {css_display:<48s} (NOT FOUND)"
                    )
                    for suggestion in sel_r.suggestions:
                        lines.append(
                            f"        {_YELLOW}-> suggestion: {suggestion}{_RESET}"
                        )
            lines.append("")

        # サマリー
        if total > 0:
            pct = (passed / total) * 100
            color = _GREEN if pct == 100 else (_YELLOW if pct >= 50 else _RED)
            lines.append(
                f"  {_BOLD}Summary: {color}{passed}/{total} selectors passed ({pct:.0f}%){_RESET}"
            )
        lines.append("")

    return "\n".join(lines)


def render_json_report(results: Sequence[ServiceResult]) -> str:
    """検証結果を JSON 文字列として返す (CI 連携等に利用)。"""

    def _sr_to_dict(sr: ServiceResult) -> dict:
        if sr.skipped:
            return {"service": sr.service, "skipped": True, "reason": sr.skip_reason}
        pages = []
        for pr in sr.pages:
            if pr.skipped:
                pages.append(
                    {"page": pr.page_type, "url": pr.url, "skipped": True, "reason": pr.skip_reason}
                )
            else:
                selectors = []
                for sel_r in pr.selectors:
                    entry: dict = {
                        "name": sel_r.name,
                        "css": sel_r.css,
                        "found": sel_r.found,
                        "count": sel_r.count,
                    }
                    if sel_r.suggestions:
                        entry["suggestions"] = sel_r.suggestions
                    selectors.append(entry)
                pages.append({"page": pr.page_type, "url": pr.url, "selectors": selectors})
        return {"service": sr.service, "pages": pages}

    payload = [_sr_to_dict(sr) for sr in results]
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify_selectors",
        description="CSS セレクタ検証ツール (Phase 6.1) - config/selectors.yaml のセレクタが実サイトで有効か検証する",
    )
    parser.add_argument(
        "--service",
        required=True,
        choices=["apple_music", "amazon_music", "all"],
        help="検証するサービス (apple_music / amazon_music / all)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="ヘッドレスモードで実行 (デフォルト: True)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        default=False,
        help="ブラウザを表示して実行",
    )
    parser.add_argument(
        "--playlist-url",
        type=str,
        default=None,
        help="プレイリストページの URL (playlist セレクタの検証に必要)",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        default=False,
        help="セレクタが見つからない場合に代替候補を提案する",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="結果を JSON 形式で出力する (CI 連携向け)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60000,
        help="ページ読み込みタイムアウト (ミリ秒, デフォルト: 60000)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="デバッグログを表示する",
    )
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> list[ServiceResult]:
    """非同期メイン処理。"""
    if args.service == "all":
        services = list(SERVICE_SECRET_MAP.keys())
    else:
        services = [args.service]

    headless = not args.no_headless
    results: list[ServiceResult] = []

    for service in services:
        print(f"\n--- Verifying selectors for: {service} ---")
        t0 = time.monotonic()
        sr = await verify_service(
            service=service,
            headless=headless,
            playlist_url=args.playlist_url,
            suggest=args.suggest,
            timeout=args.timeout,
        )
        elapsed = time.monotonic() - t0
        print(f"    (completed in {elapsed:.1f}s)")
        results.append(sr)

    return results


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    results = asyncio.run(async_main(args))

    if args.json:
        print(render_json_report(results))
    else:
        print(render_report(results))

    # 全セレクタが pass しなかったら exit code 1 (CI 向け)
    all_passed = True
    for sr in results:
        if sr.skipped:
            continue
        for pr in sr.pages:
            if pr.skipped:
                continue
            for sel_r in pr.selectors:
                if not sel_r.found:
                    all_passed = False
                    break

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
