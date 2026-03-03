#!/usr/bin/env python3
"""Apple Music ライブラリページ上のボタン/クリッカブル要素を網羅的にダンプする診断スクリプト。"""
import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.providers.playwright_helper import browser_context, load_cookies_from_secret


async def main():
    cookies = load_cookies_from_secret("apple-music-cookie")
    async with browser_context(cookies=cookies, headless=False, timeout=60_000) as (_ctx, page):
        url = "https://music.apple.com/library/playlists"
        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
        except Exception:
            pass  # タイムアウトでも続行
        await asyncio.sleep(5)

        # Edit ボタンをクリックして編集モードに入る
        edit_btn = await page.query_selector("[data-testid='navigation-items__toggler']")
        if edit_btn:
            print(">>> Clicking Edit button...")
            await edit_btn.click()
            await asyncio.sleep(2)
            print(">>> Edit mode activated. Scanning elements...\n")
        else:
            print(">>> Edit button not found, scanning as-is...\n")

        # ボタン、リンク、クリッカブル要素を全て取得
        elements = await page.evaluate("""() => {
            const results = [];
            const selectors = [
                'button',
                '[role="button"]',
                'a[href]',
                '[class*="add"]',
                '[class*="create"]',
                '[class*="new"]',
                '[class*="plus"]',
                '[aria-label]',
                'svg',
            ];
            const seen = new Set();
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    const key = el.outerHTML.slice(0, 200);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    results.push({
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        className: el.className && typeof el.className === 'string' ? el.className.slice(0, 150) : null,
                        ariaLabel: el.getAttribute('aria-label'),
                        role: el.getAttribute('role'),
                        dataTestId: el.getAttribute('data-testid'),
                        text: (el.textContent || '').trim().slice(0, 80),
                        href: el.getAttribute('href'),
                    });
                }
            }
            return results;
        }""")

        print(f"Found {len(elements)} elements:\n")
        for i, el in enumerate(elements):
            # フィルタ: 空テキスト＆aria-labelなし＆idなし は省略
            if not el.get('ariaLabel') and not el.get('id') and not el.get('text') and not el.get('dataTestId'):
                continue
            print(f"[{i}] <{el['tag']}> id={el['id']} role={el['role']} data-testid={el['dataTestId']}")
            print(f"     aria-label={el['ariaLabel']}")
            print(f"     class={el['className']}")
            print(f"     text={el['text'][:60]}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
