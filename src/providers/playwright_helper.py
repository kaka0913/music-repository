from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.utils.secret_manager import get_secret

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30_000  # 30秒


def load_cookies_from_secret(secret_id: str) -> list[dict]:
    """Secret Manager から Cookie JSON を取得してパースする。"""
    cookie_json = get_secret(secret_id)
    cookies = json.loads(cookie_json)
    if not isinstance(cookies, list):
        raise ValueError(f"Expected cookie list from secret '{secret_id}', got {type(cookies).__name__}")
    return cookies


@asynccontextmanager
async def browser_context(
    cookies: list[dict] | None = None,
    headless: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> AsyncGenerator[tuple[BrowserContext, Page], None]:
    """ブラウザ起動・Cookie注入・終了のコンテキストマネージャー。"""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=headless)
        context: BrowserContext = await browser.new_context()
        context.set_default_timeout(timeout)

        if cookies:
            await context.add_cookies(cookies)
            logger.info("Injected %d cookies into browser context", len(cookies))

        page: Page = await context.new_page()

        try:
            yield context, page
        finally:
            await context.close()
            await browser.close()
            logger.debug("Browser context closed")
