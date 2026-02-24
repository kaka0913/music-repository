#!/usr/bin/env python3
"""Cookie 半自動更新ツール。

ブラウザを起動してユーザーが手動ログイン → Cookie を自動抽出 →
GCP Secret Manager へアップロードする。

Usage:
    python tools/refresh_cookie.py --service amazon_music
    python tools/refresh_cookie.py --service apple_music
    python tools/refresh_cookie.py --service all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.providers.selector_loader import get_selectors
from src.utils.secret_manager import set_secret

SERVICE_SECRET_MAP = {
    "apple_music": "apple-music-cookie",
    "amazon_music": "amazon-music-cookie",
}


async def refresh_cookie(service: str) -> None:
    """指定サービスの Cookie を更新する。"""
    from playwright.async_api import async_playwright

    selectors = get_selectors(service)
    login_url = selectors["login_url"]
    logged_in_indicator = selectors["logged_in_indicator"]
    secret_id = SERVICE_SECRET_MAP[service]

    print(f"\n{'='*50}")
    print(f"  {service} Cookie 更新")
    print(f"{'='*50}")
    print(f"ブラウザを起動します...")
    print(f"ログインページ: {login_url}")
    print(f"手動でログインを完了してください。")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # ヘッドフルモード
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(login_url)

        # ログイン完了を待機（特定要素の出現 or URL遷移）
        print("ログイン待機中... (完了すると自動的に検知します)")
        try:
            await page.wait_for_selector(logged_in_indicator, timeout=300_000)  # 5分待機
            print("✓ ログイン検知!")
        except Exception:
            print("⚠ ログイン検知タイムアウト。現在の Cookie をそのまま取得します。")

        # Cookie を抽出
        cookies = await context.cookies()
        cookie_json = json.dumps(cookies, ensure_ascii=False, indent=2)

        # Secret Manager へアップロード
        print(f"Cookie を Secret Manager ({secret_id}) にアップロード中...")
        set_secret(secret_id, cookie_json)
        print(f"✓ {len(cookies)} 件の Cookie を更新しました!")

        await context.close()
        await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cookie 半自動更新ツール")
    parser.add_argument(
        "--service",
        required=True,
        choices=["apple_music", "amazon_music", "all"],
        help="更新するサービス (apple_music / amazon_music / all)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.service == "all":
        services = list(SERVICE_SECRET_MAP.keys())
    else:
        services = [args.service]

    for service in services:
        asyncio.run(refresh_cookie(service))

    print(f"\n{'='*50}")
    print("  全ての Cookie 更新が完了しました!")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
