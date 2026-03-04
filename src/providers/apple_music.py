from __future__ import annotations

import asyncio
import json
import logging

from src.models import Track
from src.providers.base import AuthenticationError, MusicProvider
from src.providers.playwright_helper import browser_context, load_cookies_from_secret
from src.providers.selector_loader import get_selectors
from src.utils.retry import ScrapingError

logger = logging.getLogger(__name__)

SECRET_ID = "apple-music-cookie"


def _extract_isrc_map_from_api_response(data: dict) -> dict[str, str]:
    """Apple Music API レスポンスからタイトル→ISRC のマッピングを抽出する。

    amp-api.music.apple.com のレスポンス構造:
      data[].relationships.tracks.data[].attributes.{name, isrc}
      または data[].attributes.{name, isrc} (トラック直接取得時)
    """
    isrc_map: dict[str, str] = {}

    def _extract_from_items(items: list[dict]) -> None:
        for item in items:
            attrs = item.get("attributes", {})
            name = attrs.get("name", "").strip().lower()
            isrc = attrs.get("isrc")
            if name and isrc:
                isrc_map[name] = isrc

    # パターン1: プレイリスト応答 (data[].relationships.tracks.data[])
    top_data = data.get("data", [])
    if isinstance(top_data, list):
        for entry in top_data:
            rel = entry.get("relationships", {})
            tracks_rel = rel.get("tracks", {})
            track_items = tracks_rel.get("data", [])
            if track_items:
                _extract_from_items(track_items)

            # パターン2: トラック直接 (data[].attributes.isrc)
            attrs = entry.get("attributes", {})
            if attrs.get("isrc") and attrs.get("name"):
                isrc_map[attrs["name"].strip().lower()] = attrs["isrc"]

    # パターン3: results / next ページ (results.songs.data[])
    results = data.get("results", {})
    if isinstance(results, dict):
        for section in results.values():
            if isinstance(section, dict):
                _extract_from_items(section.get("data", []))

    return isrc_map


class AppleMusicProvider(MusicProvider):
    """Apple Music スクレイピングによる MusicProvider 実装。"""

    def __init__(self) -> None:
        self._cookies: list[dict] = []
        self._selectors: dict = {}

    def authenticate(self) -> None:
        """Secret Manager から Cookie を取得。"""
        try:
            self._cookies = load_cookies_from_secret(SECRET_ID)
            self._selectors = get_selectors("apple_music")
            logger.info("Apple Music authentication prepared (%d cookies loaded)", len(self._cookies))
        except Exception as e:
            raise AuthenticationError(f"Apple Music authentication failed: {e}") from e

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        """プレイリストページをスクレイピングして曲目を取得。playlist_id は URL。"""
        return asyncio.get_event_loop().run_until_complete(
            self._get_playlist_tracks_async(playlist_id)
        )

    async def _get_playlist_tracks_async(self, playlist_url: str) -> list[Track]:
        tracks: list[Track] = []
        sel = self._selectors
        isrc_map: dict[str, str] = {}

        async def _on_response(response) -> None:
            """amp-api のレスポンスから ISRC を収集。"""
            url = response.url
            if "amp-api.music.apple.com" not in url:
                return
            try:
                if response.status == 200 and "json" in response.headers.get("content-type", ""):
                    body = await response.json()
                    extracted = _extract_isrc_map_from_api_response(body)
                    isrc_map.update(extracted)
                    if extracted:
                        logger.debug("Extracted %d ISRCs from Apple Music API", len(extracted))
            except Exception:
                pass  # レスポンスの読み取り失敗は無視

        try:
            async with browser_context(cookies=self._cookies) as (ctx, page):
                page.on("response", _on_response)
                await page.goto(playlist_url, wait_until="domcontentloaded")

                # SPA レンダリング待機
                try:
                    await page.wait_for_selector(sel["playlist_track_row"], timeout=30_000)
                except Exception:
                    logger.debug("Apple Music: playlist_track_row not found within timeout")

                # ログイン状態の確認
                logged_in = await page.query_selector(sel["logged_in_indicator"])
                if not logged_in:
                    raise AuthenticationError("Apple Music: not logged in. Cookie may be expired.")

                # トラック行を取得
                rows = await page.query_selector_all(sel["playlist_track_row"])
                if not rows:
                    logger.warning("Apple Music: No track rows found for selector '%s'", sel["playlist_track_row"])

                for row in rows:
                    title_el = await row.query_selector(sel["track_title"])
                    artist_el = await row.query_selector(sel["track_artist"])

                    title = (await title_el.inner_text()).strip() if title_el else ""
                    artist = (await artist_el.inner_text()).strip() if artist_el else ""

                    # インターセプトした API レスポンスから ISRC を照合
                    isrc = isrc_map.get(title.lower())

                    tracks.append(Track(
                        isrc=isrc,
                        title=title,
                        artist=artist,
                        album="",
                        service_ids={"apple_music": playlist_url},
                    ))
        except TimeoutError as e:
            raise ScrapingError(f"Apple Music: page load timed out for {playlist_url}: {e}") from e

        matched = sum(1 for t in tracks if t.isrc)
        logger.info("Retrieved %d tracks from Apple Music playlist (%d with ISRC)", len(tracks), matched)
        return tracks

    def add_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """検索 → プレイリストに追加のブラウザ操作。"""
        asyncio.get_event_loop().run_until_complete(
            self._add_tracks_async(playlist_id, tracks)
        )

    async def _add_tracks_async(self, playlist_url: str, tracks: list[Track]) -> None:
        sel = self._selectors

        async with browser_context(cookies=self._cookies) as (ctx, page):
            for track in tracks:
                # 検索ページへ遷移
                await page.goto("https://music.apple.com/search", wait_until="domcontentloaded")

                search_input = await page.wait_for_selector(sel["search_input"], timeout=15_000)
                await search_input.fill(f"{track.title} {track.artist}")
                await search_input.press("Enter")

                # 検索結果の表示を待機
                try:
                    await page.wait_for_selector(sel["search_result_row"], timeout=15_000)
                except Exception:
                    pass

                # 最初の検索結果を選択
                result_row = await page.query_selector(sel["search_result_row"])
                if not result_row:
                    logger.warning("No search result for '%s' by %s on Apple Music", track.title, track.artist)
                    continue

                # プレイリストに追加
                add_button = await result_row.query_selector(sel["add_to_playlist_button"])
                if add_button:
                    await add_button.click()
                    logger.info("Added '%s' to Apple Music playlist", track.title)

    def remove_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストから楽曲を削除するブラウザ操作。"""
        asyncio.get_event_loop().run_until_complete(
            self._remove_tracks_async(playlist_id, tracks)
        )

    async def _remove_tracks_async(self, playlist_url: str, tracks: list[Track]) -> None:
        async with browser_context(cookies=self._cookies) as (ctx, page):
            await page.goto(playlist_url, wait_until="domcontentloaded")

            sel = self._selectors
            try:
                await page.wait_for_selector(sel["playlist_track_row"], timeout=30_000)
            except Exception:
                pass
            rows = await page.query_selector_all(sel["playlist_track_row"])
            track_titles_to_remove = {t.title.lower() for t in tracks}

            for row in rows:
                title_el = await row.query_selector(sel["track_title"])
                if title_el:
                    title = (await title_el.inner_text()).strip()
                    if title.lower() in track_titles_to_remove:
                        # 右クリックメニューから削除を試行
                        await row.click(button="right")
                        delete_option = await page.query_selector("text=削除")
                        if not delete_option:
                            delete_option = await page.query_selector("text=Remove")
                        if delete_option:
                            await delete_option.click()
                            logger.info("Removed '%s' from Apple Music playlist", title)

    def search_track(self, title: str, artist: str) -> Track | None:
        """Apple Music 検索を利用した楽曲検索。"""
        return asyncio.get_event_loop().run_until_complete(
            self._search_track_async(title, artist)
        )

    async def _search_track_async(self, title: str, artist: str) -> Track | None:
        sel = self._selectors
        isrc_map: dict[str, str] = {}

        async def _on_response(response) -> None:
            url = response.url
            if "amp-api.music.apple.com" not in url:
                return
            try:
                if response.status == 200 and "json" in response.headers.get("content-type", ""):
                    body = await response.json()
                    isrc_map.update(_extract_isrc_map_from_api_response(body))
            except Exception:
                pass

        async with browser_context(cookies=self._cookies) as (ctx, page):
            page.on("response", _on_response)
            await page.goto("https://music.apple.com/search", wait_until="domcontentloaded")

            search_input = await page.wait_for_selector(sel["search_input"], timeout=15_000)
            await search_input.fill(f"{title} {artist}")
            await search_input.press("Enter")

            # 検索結果の表示を待機
            try:
                await page.wait_for_selector(sel["search_result_row"], timeout=15_000)
            except Exception:
                pass

            result_row = await page.query_selector(sel["search_result_row"])
            if not result_row:
                return None

            title_el = await result_row.query_selector(sel["track_title"])
            artist_el = await result_row.query_selector(sel["track_artist"])

            found_title = (await title_el.inner_text()).strip() if title_el else title
            found_artist = (await artist_el.inner_text()).strip() if artist_el else artist

            isrc = isrc_map.get(found_title.lower())

            return Track(
                isrc=isrc,
                title=found_title,
                artist=found_artist,
                album="",
                service_ids={"apple_music": None},
            )

    def get_all_playlists(self) -> list[tuple[str, str]]:
        """ライブラリページからプレイリスト一覧を取得。"""
        return asyncio.get_event_loop().run_until_complete(
            self._get_all_playlists_async()
        )

    async def _get_all_playlists_async(self) -> list[tuple[str, str]]:
        sel = self._selectors
        playlists: list[tuple[str, str]] = []

        try:
            async with browser_context(cookies=self._cookies, timeout=60_000) as (ctx, page):
                try:
                    await page.goto("https://music.apple.com/library/playlists", wait_until="domcontentloaded", timeout=60_000)
                except Exception:
                    pass

                # SPA レンダリング待機: domcontentloaded 後に JS がコンテンツを生成するため
                await asyncio.sleep(10)

                # セレクターの出現を待機
                try:
                    await page.wait_for_selector(sel["library_playlist_row"], timeout=30_000)
                except Exception:
                    logger.debug("Apple Music: library_playlist_row selector not found within timeout")

                logged_in = await page.query_selector(sel["logged_in_indicator"])
                if not logged_in:
                    raise AuthenticationError("Apple Music: not logged in. Cookie may be expired.")

                rows = await page.query_selector_all(sel["library_playlist_row"])
                for row in rows:
                    name_el = await row.query_selector(sel["library_playlist_name"])
                    link_el = await row.query_selector(sel["library_playlist_link"])

                    name = (await name_el.inner_text()).strip() if name_el else ""
                    href = await link_el.get_attribute("href") if link_el else ""

                    if name and href:
                        if href.startswith("/"):
                            href = f"https://music.apple.com{href}"
                        playlists.append((name, href))

                # メインコンテンツが空の場合、サイドバーのプレイリストリンクを取得
                if not playlists:
                    logger.debug("Apple Music: main content empty, trying sidebar navigation")
                    sidebar_links = await page.query_selector_all("a[href*='/library/playlist/']")
                    for link in sidebar_links:
                        name = (await link.inner_text()).strip()
                        href = await link.get_attribute("href") or ""
                        if name and href and "/all-playlists" not in href:
                            if href.startswith("/"):
                                href = f"https://music.apple.com{href}"
                            playlists.append((name, href))
        except TimeoutError as e:
            raise ScrapingError(f"Apple Music: library page load timed out: {e}") from e

        logger.info("Discovered %d playlists from Apple Music", len(playlists))
        return playlists

    def create_playlist(self, name: str) -> str:
        """新しいプレイリストを作成し、その URL を返す。

        Apple Music Web はプレイリスト作成機能を提供していないため、
        ScrapingError を送出してスキップさせる。
        """
        raise ScrapingError(
            f"Apple Music: Web 版ではプレイリスト作成がサポートされていません。"
            f"プレイリスト '{name}' は Apple Music アプリ (iOS/Mac) で手動作成してください。"
        )
