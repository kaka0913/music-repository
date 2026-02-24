from __future__ import annotations

import asyncio
import logging

from src.models import Track
from src.providers.base import AuthenticationError, MusicProvider
from src.providers.playwright_helper import browser_context, load_cookies_from_secret
from src.providers.selector_loader import get_selectors

logger = logging.getLogger(__name__)

SECRET_ID = "amazon-music-cookie"


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

        async with browser_context(cookies=self._cookies) as (ctx, page):
            await page.goto(playlist_url, wait_until="networkidle")

            logged_in = await page.query_selector(sel["logged_in_indicator"])
            if not logged_in:
                raise AuthenticationError("Amazon Music: not logged in. Cookie may be expired.")

            rows = await page.query_selector_all(sel["playlist_track_row"])
            for row in rows:
                title_el = await row.query_selector(sel["track_title"])
                artist_el = await row.query_selector(sel["track_artist"])

                title = (await title_el.inner_text()).strip() if title_el else ""
                artist = (await artist_el.inner_text()).strip() if artist_el else ""

                tracks.append(Track(
                    isrc=None,
                    title=title,
                    artist=artist,
                    album="",
                    service_ids={"amazon_music": playlist_url},
                ))

        logger.info("Retrieved %d tracks from Amazon Music playlist", len(tracks))
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

        async with browser_context(cookies=self._cookies) as (ctx, page):
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

            return Track(
                isrc=None,
                title=found_title,
                artist=found_artist,
                album="",
                service_ids={"amazon_music": None},
            )
