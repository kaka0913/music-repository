"""Spotify OAuth リフレッシュトークン取得スクリプト（初回のみ使用）。

使い方:
  export SPOTIFY_CLIENT_ID="your_client_id"
  export SPOTIFY_CLIENT_SECRET="your_client_secret"

  # ステップ1: 認可URLを表示
  python tools/spotify_auth.py

  # ステップ2: ブラウザで認可後、リダイレクトURLを引数に渡す
  python tools/spotify_auth.py "https://github.com/callback?code=AQD..."

Spotify Developer Dashboard の Redirect URI に以下を登録:
  https://github.com/callback
"""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlparse

import spotipy
from spotipy.oauth2 import SpotifyOAuth

REDIRECT_URI = "https://github.com/callback"
SCOPE = "playlist-read-private playlist-modify-private playlist-modify-public"


def main() -> None:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: SPOTIFY_CLIENT_ID と SPOTIFY_CLIENT_SECRET を環境変数にセットしてください")
        sys.exit(1)

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
    )

    # 引数なし → 認可URLを表示
    if len(sys.argv) < 2:
        url = auth.get_authorize_url()
        print(f"\n1. 以下のURLをブラウザで開いてください:\n")
        print(f"   {url}\n")
        print("2. Spotify にログインして許可してください")
        print("3. リダイレクト先のページは表示エラーになりますが、それでOKです")
        print("4. ブラウザのアドレスバーからURL全体をコピーしてください")
        print("5. 以下のコマンドを実行してください:\n")
        print(f'   python tools/spotify_auth.py "コピーしたURL"')
        return

    # 引数あり → リダイレクトURLからコードを抽出してトークン取得
    redirect_url = sys.argv[1]
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    if "code" not in params:
        print("ERROR: URLに code パラメータが見つかりません")
        print(f"  受け取ったURL: {redirect_url}")
        sys.exit(1)

    code = params["code"][0]
    print(f"認可コードを取得しました")

    token_info = auth.get_access_token(code, as_dict=True)
    refresh_token = token_info["refresh_token"]

    # 認証テスト
    sp = spotipy.Spotify(auth=token_info["access_token"])
    user = sp.current_user()
    print(f"\n=== 認証成功 ===")
    print(f"ユーザー: {user['display_name']} ({user['id']})")
    print(f"\nRefresh Token: {refresh_token}")
    print(f"\nGCP Secret Manager に保存:")
    print(f"  echo -n '{refresh_token}' | gcloud secrets versions add spotify-refresh-token --data-file=-")

    # .cache ファイルがあれば削除
    if os.path.exists(".cache"):
        os.remove(".cache")


if __name__ == "__main__":
    main()
