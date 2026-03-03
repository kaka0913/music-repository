# Music Playlist Hub

Spotify / Apple Music / Amazon Music 間でプレイリストを自動同期するツール。

GitHub Actions (cron) で毎日実行し、指定したプレイリストの楽曲を各サービス間で揃える。

## 仕組み

```
Spotify  ──┐
Apple    ──┼── 楽曲取得 → 差分検知 → 不足分を各サービスに追加/削除
Amazon   ──┘
```

- **ISRC** (国際標準レコーディングコード) で楽曲を照合。取得できない場合はタイトル+アーティスト名で検索
- **差分ベース**: 前回の状態 (`state/`) と比較して追加・削除のみ実行
- **競合解決**: 複数サービスで同時に変更があった場合、タイムスタンプの新しい方を優先

## 同期対象

`config/playlists.yaml` で指定:
サービスには初回実行時にプレイリストが自動作成される。

## セットアップ

### 必要なもの

- Python 3.12+
- GCP プロジェクト (Secret Manager)
- Spotify Developer App
- Apple Music / Amazon Music のログイン Cookie

### インストール

```bash
pip install -r requirements.txt
playwright install chromium
```

### シークレット

| シークレット | 保存先 | 用途 |
|-------------|--------|------|
| `SPOTIFY_CLIENT_ID` | GitHub Secrets | Spotify API |
| `SPOTIFY_CLIENT_SECRET` | GitHub Secrets | Spotify API |
| `GCP_SA_KEY` | GitHub Secrets | GCP 認証 |
| `GCP_PROJECT_ID` | GitHub Secrets | GCP プロジェクト ID |
| `NOTIFICATION_EMAIL` | GitHub Secrets | エラー通知先 |
| `GMAIL_APP_PASSWORD` | GitHub Secrets | メール送信 |
| `spotify-refresh-token` | GCP Secret Manager | Spotify OAuth |
| `apple-music-cookie` | GCP Secret Manager | Apple Music 認証 |
| `amazon-music-cookie` | GCP Secret Manager | Amazon Music 認証 |

## 運用

- **自動実行**: GitHub Actions で毎日 UTC 3:00 (JST 12:00)
- **手動実行**: `gh workflow run sync.yml`
- **Cookie 更新**: `python tools/refresh_cookie.py --service apple_music`
- **セレクター検証**: `python tools/verify_selectors.py --service all --suggest`
- **エラー通知**: 同期失敗時にメールで通知

## ディレクトリ構成

```
src/
  main.py              # エントリーポイント
  providers/
    spotify.py         # Spotify API (spotipy)
    apple_music.py     # Apple Music (Playwright)
    amazon_music.py    # Amazon Music (Playwright)
  sync_engine.py       # 差分検知・同期実行
  discovery.py         # プレイリスト自動発見
  notification.py      # エラー通知メール
config/
  playlists.yaml       # 同期対象プレイリスト
  selectors.yaml       # CSS セレクター定義
state/                 # 同期状態 (自動更新)
tools/                 # 運用ツール群
```
