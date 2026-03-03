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

SECRET_ID = "amazon-music-cookie"


def _extract_isrc_map_from_api_response(data: dict) -> dict[str, dict[str, str]]:
    """Amazon Music API レスポンスからタイトル→{isrc, asin} のマッピングを抽出する。

    Amazon Music の内部 API (Maestro/Coral) のレスポンス構造:
      methods[].template.widgets[].items[].{title, isrc, asin}
      または tracks[].metadata.{title, isrc, asin}
      または results[].{title, isrc, asin}
    """
    track_map: dict[str, dict[str, str]] = {}

    def _extract_from_item(item: dict) -> None:
        """単一トラックアイテムから ISRC/ASIN を抽出。"""
        # メタデータの取得（ネスト構造に対応）
        metadata = item.get("metadata", item)
        title = (
            metadata.get("title", "")
            or metadata.get("name", "")
            or item.get("title", "")
        ).strip().lower()
        if not title:
            return

        isrc = metadata.get("isrc") or item.get("isrc")
        asin = metadata.get("asin") or item.get("asin") or item.get("catalogId")

        if isrc or asin:
            existing = track_map.get(title, {})
            track_map[title] = {
                "isrc": isrc or existing.get("isrc"),
                "asin": asin or existing.get("asin"),
            }

    def _walk(obj: dict | list) -> None:
        """レスポンス内のトラックデータを再帰的に探索。"""
        if isinstance(obj, dict):
            # トラックらしき構造を検出
            if ("title" in obj or "name" in obj) and ("isrc" in obj or "asin" in obj or "catalogId" in obj):
                _extract_from_item(obj)
            if "metadata" in obj and isinstance(obj["metadata"], dict):
                _extract_from_item(obj)
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    _walk(item)

    _walk(data)
    return track_map


class AmazonMusicProvider(MusicProvider):
    """Amazon Music スクレイピングによる MusicProvider 実装。"""

    def __init__(self) -> None:
        self._cookies: list[dict] = []
        self._selectors: dict = {}

    def authenticate(self) -> None:
        """Secret Manager から Cookie を取得。"""
        try:
            self._cookies = load_cookies_from_secret(SECRET_ID)
            self._selectors = get_selectors("amazon_music")
            logger.info("Amazon Music authentication prepared (%d cookies loaded)", len(self._cookies))
        except Exception as e:
            raise AuthenticationError(f"Amazon Music authentication failed: {e}") from e

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        """プレイリストページをスクレイピングして曲目を取得。playlist_id は URL。"""
        return asyncio.get_event_loop().run_until_complete(
            self._get_playlist_tracks_async(playlist_id)
        )

    async def _get_playlist_tracks_async(self, playlist_url: str) -> list[Track]:
        tracks: list[Track] = []
        sel = self._selectors
        api_track_map: dict[str, dict[str, str]] = {}

        async def _on_response(response) -> None:
            """Amazon Music API レスポンスから ISRC/ASIN を収集。"""
            url = response.url
            if not any(domain in url for domain in ("music.amazon", "music.a2z.com", "mesk.skill")):
                return
            try:
                content_type = response.headers.get("content-type", "")
                if response.status == 200 and "json" in content_type:
                    body = await response.json()
                    extracted = _extract_isrc_map_from_api_response(body)
                    api_track_map.update(extracted)
                    if extracted:
                        logger.debug("Extracted %d track metadata from Amazon Music API", len(extracted))
            except Exception:
                pass

        try:
            async with browser_context(cookies=self._cookies) as (ctx, page):
                page.on("response", _on_response)
                await page.goto(playlist_url, wait_until="networkidle")

                logged_in = await page.query_selector(sel["logged_in_indicator"])
                if not logged_in:
                    raise AuthenticationError("Amazon Music: not logged in. Cookie may be expired.")

                rows = await page.query_selector_all(sel["playlist_track_row"])
                if not rows:
                    logger.warning("Amazon Music: No track rows found for selector '%s'", sel["playlist_track_row"])

                for row in rows:
                    title_el = await row.query_selector(sel["track_title"])
                    artist_el = await row.query_selector(sel["track_artist"])

                    title = (await title_el.inner_text()).strip() if title_el else ""
                    artist = (await artist_el.inner_text()).strip() if artist_el else ""

                    # 遅延ロード未完了の空行をスキップ
                    if not title:
                        continue

                    # API レスポンスから ISRC/ASIN を照合
                    meta = api_track_map.get(title.lower(), {})
                    isrc = meta.get("isrc")
                    asin = meta.get("asin")

                    service_ids: dict[str, str | None] = {"amazon_music": playlist_url}
                    if asin:
                        service_ids["amazon_music_asin"] = asin

                    tracks.append(Track(
                        isrc=isrc,
                        title=title,
                        artist=artist,
                        album="",
                        service_ids=service_ids,
                    ))
        except TimeoutError as e:
            raise ScrapingError(f"Amazon Music: page load timed out for {playlist_url}: {e}") from e

        matched = sum(1 for t in tracks if t.isrc)
        logger.info("Retrieved %d tracks from Amazon Music playlist (%d with ISRC, %d with ASIN)",
                     len(tracks), matched, sum(1 for t in tracks if t.service_ids.get("amazon_music_asin")))
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
                await page.goto("https://music.amazon.co.jp", wait_until="networkidle")

                search_input = await page.wait_for_selector(sel["search_input"])
                await search_input.fill(f"{track.title} {track.artist}")
                await search_input.press("Enter")
                await page.wait_for_load_state("networkidle")

                result_row = await page.query_selector(sel["search_result_row"])
                if not result_row:
                    logger.warning("No search result for '%s' by %s on Amazon Music", track.title, track.artist)
                    continue

                add_button = await result_row.query_selector(sel["add_to_playlist_button"])
                if add_button:
                    await add_button.click()
                    logger.info("Added '%s' to Amazon Music playlist", track.title)

    def remove_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストから楽曲を削除するブラウザ操作。"""
        asyncio.get_event_loop().run_until_complete(
            self._remove_tracks_async(playlist_id, tracks)
        )

    async def _remove_tracks_async(self, playlist_url: str, tracks: list[Track]) -> None:
        async with browser_context(cookies=self._cookies) as (ctx, page):
            await page.goto(playlist_url, wait_until="networkidle")

            sel = self._selectors
            rows = await page.query_selector_all(sel["playlist_track_row"])
            track_titles_to_remove = {t.title.lower() for t in tracks}

            for row in rows:
                title_el = await row.query_selector(sel["track_title"])
                if title_el:
                    title = (await title_el.inner_text()).strip()
                    if title.lower() in track_titles_to_remove:
                        await row.click(button="right")
                        delete_option = await page.query_selector("text=削除")
                        if not delete_option:
                            delete_option = await page.query_selector("text=Remove")
                        if delete_option:
                            await delete_option.click()
                            logger.info("Removed '%s' from Amazon Music playlist", title)

    def search_track(self, title: str, artist: str) -> Track | None:
        """Amazon Music 検索を利用した楽曲検索。"""
        return asyncio.get_event_loop().run_until_complete(
            self._search_track_async(title, artist)
        )

    async def _search_track_async(self, title: str, artist: str) -> Track | None:
        sel = self._selectors
        api_track_map: dict[str, dict[str, str]] = {}

        async def _on_response(response) -> None:
            url = response.url
            if not any(domain in url for domain in ("music.amazon", "music.a2z.com", "mesk.skill")):
                return
            try:
                content_type = response.headers.get("content-type", "")
                if response.status == 200 and "json" in content_type:
                    body = await response.json()
                    api_track_map.update(_extract_isrc_map_from_api_response(body))
            except Exception:
                pass

        async with browser_context(cookies=self._cookies) as (ctx, page):
            page.on("response", _on_response)
            await page.goto("https://music.amazon.co.jp", wait_until="networkidle")

            search_input = await page.wait_for_selector(sel["search_input"])
            await search_input.fill(f"{title} {artist}")
            await search_input.press("Enter")
            await page.wait_for_load_state("networkidle")

            result_row = await page.query_selector(sel["search_result_row"])
            if not result_row:
                return None

            title_el = await result_row.query_selector(sel["track_title"])
            artist_el = await result_row.query_selector(sel["track_artist"])

            found_title = (await title_el.inner_text()).strip() if title_el else title
            found_artist = (await artist_el.inner_text()).strip() if artist_el else artist

            meta = api_track_map.get(found_title.lower(), {})
            isrc = meta.get("isrc")
            asin = meta.get("asin")

            service_ids: dict[str, str | None] = {"amazon_music": None}
            if asin:
                service_ids["amazon_music_asin"] = asin

            return Track(
                isrc=isrc,
                title=found_title,
                artist=found_artist,
                album="",
                service_ids=service_ids,
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
            async with browser_context(cookies=self._cookies) as (ctx, page):
                await page.goto("https://music.amazon.co.jp/my/playlists", wait_until="networkidle")

                logged_in = await page.query_selector(sel["logged_in_indicator"])
                if not logged_in:
                    raise AuthenticationError("Amazon Music: not logged in. Cookie may be expired.")

                rows = await page.query_selector_all(sel["library_playlist_row"])
                for row in rows:
                    name_el = await row.query_selector(sel["library_playlist_name"])
                    link_el = await row.query_selector(sel["library_playlist_link"])

                    name = (await name_el.inner_text()).strip() if name_el else ""
                    href = await link_el.get_attribute("href") if link_el else ""

                    if name and href:
                        if href.startswith("/"):
                            href = f"https://music.amazon.co.jp{href}"
                        playlists.append((name, href))
        except TimeoutError as e:
            raise ScrapingError(f"Amazon Music: library page load timed out: {e}") from e

        logger.info("Discovered %d playlists from Amazon Music", len(playlists))
        return playlists

    def create_playlist(self, name: str) -> str:
        """新しいプレイリストを作成し、その URL を返す。"""
        return asyncio.get_event_loop().run_until_complete(
            self._create_playlist_async(name)
        )

    async def _create_playlist_async(self, name: str) -> str:
        sel = self._selectors

        try:
            async with browser_context(cookies=self._cookies) as (ctx, page):
                await page.goto("https://music.amazon.co.jp/my/playlists", wait_until="networkidle")

                new_btn = await page.wait_for_selector(sel["new_playlist_button"], timeout=10000)
                await new_btn.click()

                name_input = await page.wait_for_selector(sel["new_playlist_name_input"], timeout=10000)
                await name_input.fill(name)

                confirm_btn = await page.wait_for_selector(sel["new_playlist_confirm"], timeout=10000)
                await confirm_btn.click()
                await page.wait_for_load_state("networkidle")

                playlist_url = page.url
                logger.info("Created Amazon Music playlist '%s' (url=%s)", name, playlist_url)
                return playlist_url
        except TimeoutError as e:
            raise ScrapingError(f"Amazon Music: playlist creation timed out: {e}") from e
