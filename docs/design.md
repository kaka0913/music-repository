# Music Playlist Hub (Synchronizer) - 設計書

## 1. システムアーキテクチャ

### 1.1 全体構成

* **GitHub Actions** (Cron) が `config/playlists.yaml` を読み込み、`SyncEngine` を起動する。
* `SyncEngine` は各 `MusicProvider`（Spotify / Apple Music / Amazon Music）を介して楽曲を取得・反映する。
* Spotify は Web API（spotipy）、Apple Music / Amazon Music は Playwright によるスクレイピングで接続する。
* 認証情報は **GCP Secret Manager** から取得する（Spotify OAuth トークン、Apple/Amazon の Cookie、Gmail アプリパスワード）。
* 同期結果は `state/*.json` に書き出し、変更があれば Git commit & push する。

### 1.2 コンポーネント一覧

| コンポーネント | 責務 |
|---|---|
| `main.py` | エントリーポイント。設定読み込み → 同期実行 → 状態保存のオーケストレーション |
| `sync_engine.py` | 差分検知・競合解決・反映指示のコアロジック |
| `models.py` | `Track`, `Playlist`, `SyncResult` などのデータクラス定義 |
| `config_loader.py` | `playlists.yaml` のパースとバリデーション |
| `notification.py` | Gmail SMTP経由のエラー通知メール送信 |
| `providers/base.py` | 全プロバイダー共通の抽象基底クラス |
| `providers/spotify.py` | Spotify Web API連携（spotipy使用） |
| `providers/apple_music.py` | Apple Music スクレイピング（Playwright使用） |
| `providers/amazon_music.py` | Amazon Music スクレイピング（Playwright使用） |
| `utils/isrc.py` | ISRCマッチング・メタデータフォールバック検索 |
| `utils/secret_manager.py` | GCP Secret Managerからの認証情報取得・更新 |
| `tools/refresh_cookie.py` | Cookie半自動更新CLIツール |

---

## 2. ディレクトリ構成

```
MusicRepository/
├── .github/
│   └── workflows/
│       └── sync.yml              # 定期同期ジョブ
├── config/
│   └── playlists.yaml            # 同期対象プレイリスト定義
├── state/
│   └── {playlist_name}.json      # 各プレイリストの最新状態
├── src/
│   ├── main.py                   # エントリーポイント
│   ├── sync_engine.py            # 差分検知・同期ロジック
│   ├── models.py                 # データモデル定義
│   ├── config_loader.py          # 設定ファイル読み込み
│   ├── notification.py           # メール通知
│   ├── providers/
│   │   ├── base.py               # プロバイダー共通インターフェース
│   │   ├── spotify.py            # Spotify API連携
│   │   ├── apple_music.py        # Apple Music スクレイピング
│   │   └── amazon_music.py       # Amazon Music スクレイピング
│   └── utils/
│       ├── isrc.py               # ISRC照合・フォールバック検索
│       └── secret_manager.py     # GCP Secret Manager連携
├── tools/
│   └── refresh_cookie.py         # Cookie半自動更新CLIツール
├── tests/
│   ├── test_sync_engine.py
│   ├── test_config_loader.py
│   └── test_providers/
├── requirements.txt
├── requirement.md
├── design.md
└── README.md
```

---

## 3. 技術スタック

| カテゴリ | 技術 | 用途 |
|---|---|---|
| Language | Python 3.12+ | 全ロジック |
| CI/CD | GitHub Actions | 定期実行・同期ジョブ |
| Cloud | GCP Secret Manager | 認証情報の安全な保管 |
| Spotify | `spotipy` | Spotify Web API ラッパー |
| Apple Music | `playwright` | ブラウザ自動操作によるスクレイピング |
| Amazon Music | `playwright` | ブラウザ自動操作によるスクレイピング |
| メール通知 | `smtplib` (標準ライブラリ) | Gmail SMTPによるアラート送信 |
| Secret管理 | `google-cloud-secret-manager` | GCP Secret Manager SDK |
| 設定管理 | `pyyaml` | playlists.yaml の読み込み |
| テスト | `pytest` | ユニットテスト |

---

## 4. データモデル

### 4.1 設定ファイル (`config/playlists.yaml`)

```yaml
playlists:
  - name: "Favorites 2025"
    spotify:
      playlist_id: "37i9dQZF1DXcBWIGoYBM5M"
    apple_music:
      playlist_url: "https://music.apple.com/jp/playlist/..."
    amazon_music:
      playlist_url: "https://music.amazon.co.jp/user-playlists/..."

  - name: "Workout Mix"
    spotify:
      playlist_id: "5ABHKGoOzxkaa28ttQV9sE"
    apple_music:
      playlist_url: "https://music.apple.com/jp/playlist/..."
    amazon_music:
      playlist_url: "https://music.amazon.co.jp/user-playlists/..."

notification:
  email: "user@example.com"
  smtp_host: "smtp.gmail.com"
  smtp_port: 587

sync:
  cron: "0 3 * * *"
```

### 4.2 状態ファイル (`state/{playlist_name}.json`)

```json
{
  "playlist_name": "Favorites 2025",
  "last_synced_at": "2025-07-01T03:00:00Z",
  "tracks": [
    {
      "isrc": "USUM72400001",
      "title": "Song Title",
      "artist": "Artist Name",
      "album": "Album Name",
      "service_ids": {
        "spotify": "4iV5W9uYEdYUVa79Axb7Rh",
        "apple_music": "1440935791",
        "amazon_music": "B0XXXXXXXX"
      },
      "added_at": "2025-06-15T10:30:00Z"
    }
  ],
  "unmatched": [
    {
      "source_service": "spotify",
      "title": "Rare Song",
      "artist": "Indie Artist",
      "isrc": null,
      "reason": "No match found on apple_music, amazon_music",
      "detected_at": "2025-07-01T03:00:00Z"
    }
  ]
}
```

### 4.3 フィールド定義

#### tracks[]

| フィールド | 型 | 説明 |
|---|---|---|
| `isrc` | `string \| null` | 国際標準レコーディングコード。取得不可の場合は `null` |
| `title` | `string` | 曲名 |
| `artist` | `string` | アーティスト名 |
| `album` | `string` | アルバム名 |
| `service_ids` | `object` | 各サービスでの楽曲ID。未登録サービスのキーは `null` |
| `added_at` | `string \| null` | プレイリストへの追加日時（ISO 8601）。取得不可の場合は `null` |

#### unmatched[]

| フィールド | 型 | 説明 |
|---|---|---|
| `source_service` | `string` | マッチ対象の楽曲が存在するサービス名 |
| `title` | `string` | 曲名 |
| `artist` | `string` | アーティスト名 |
| `isrc` | `string \| null` | ISRC（取得できた場合） |
| `reason` | `string` | マッチ失敗の理由 |
| `detected_at` | `string` | 検知日時（ISO 8601） |

---

## 5. プロバイダーインターフェース設計

全サービスプロバイダーは共通の抽象基底クラスを実装する。

```python
from abc import ABC, abstractmethod
from models import Track

class MusicProvider(ABC):
    """音楽サービスプロバイダーの共通インターフェース"""

    @abstractmethod
    def authenticate(self) -> None:
        """認証を実行。失敗時は AuthenticationError を送出。"""

    @abstractmethod
    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        """指定プレイリストの全楽曲を取得。"""

    @abstractmethod
    def add_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストに楽曲を追加。"""

    @abstractmethod
    def remove_tracks(self, playlist_id: str, tracks: list[Track]) -> None:
        """プレイリストから楽曲を削除。"""

    @abstractmethod
    def search_track(self, title: str, artist: str) -> Track | None:
        """曲名+アーティスト名で楽曲を検索（ISRCフォールバック用）。"""
```

### 5.1 プロバイダー別実装方針

#### Spotify (`providers/spotify.py`)

* `spotipy` ライブラリでSpotify Web APIを利用。
* OAuth 2.0 Authorization Code Flow でトークンを取得。
* リフレッシュトークンをGCP Secret Managerに保管し、自動更新。
* ISRCは `track.external_ids['isrc']` から取得可能。

#### Apple Music (`providers/apple_music.py`)

* Playwrightでブラウザを起動し、Cookie注入でログイン状態を再現。
* プレイリストページから曲目リストをスクレイピング。
* 楽曲追加・削除もブラウザ操作で実行。
* ISRCは検索API or ページ内メタデータから取得を試みる。

#### Amazon Music (`providers/amazon_music.py`)

* Playwrightでブラウザを起動し、Cookie注入でログイン状態を再現。
* プレイリストページから曲目リストをスクレイピング。
* 楽曲追加・削除もブラウザ操作で実行。
* ISRCはページ内メタデータまたはASIN経由で取得を試みる。

---

## 6. 同期アルゴリズム

### 6.1 メインフロー

```
1. config/playlists.yaml を読み込む
2. GCP Secret Manager から認証情報を取得
3. 各プロバイダーで authenticate() を実行
   └─ 失敗 → エラー通知メール送信 → ジョブ終了

4. プレイリストごとにループ:
   a. 各サービスから現在の曲目を取得 (get_playlist_tracks)
   b. state/{name}.json から前回状態を読み込み
   c. 差分を計算 (diff)
   d. 競合を解決 (resolve_conflicts)
   e. 各サービスへ反映 (add_tracks / remove_tracks)
   f. state/{name}.json を更新

5. 変更があれば git commit & push
6. 未同期楽曲・エラーがあればメール通知
```

### 6.2 差分検知ロジック

各サービスについて、前回状態と現在状態をISRC（またはservice_id）で比較する。

```
previous = state/{name}.json の tracks (ISRCセット)
current  = get_playlist_tracks() の結果 (ISRCセット)

added_on_{service}   = current - previous   # サービス側で追加された曲
removed_on_{service} = previous - current   # サービス側で削除された曲
```

### 6.3 競合解決ロジック

```
同一ISRCについて:
  サービスAで追加 & サービスBで削除 の場合:

  1. 両方の added_at タイムスタンプを比較
     → 新しい方の操作を採用

  2. 片方のみタイムスタンプあり
     → タイムスタンプがある方を採用

  3. 両方ともタイムスタンプなし
     → 追加を優先（安全策）
```

### 6.4 反映ロジック

```
各サービス S について:
  to_add    = 他サービスで追加された曲のうち S に存在しないもの
  to_remove = 他サービスで削除された曲のうち S にまだ存在するもの

  for track in to_add:
    1. S で ISRC検索
    2. 見つからなければ 曲名+アーティスト名 で検索
    3. 見つかれば add_tracks() で追加、service_id を記録
    4. 見つからなければ unmatched に記録

  for track in to_remove:
    S.remove_tracks(track)
```

---

## 7. GitHub Actions ワークフロー

### 7.1 sync.yml

```yaml
name: Playlist Sync

on:
  schedule:
    - cron: "0 3 * * *"    # 毎日 AM3:00 UTC
  workflow_dispatch:        # 手動実行も可能

permissions:
  contents: write           # state/*.json のコミット＆プッシュ用

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Install Playwright browsers
        run: playwright install chromium

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Run sync
        run: python src/main.py
        env:
          SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
          SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
          GCP_PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
          NOTIFICATION_EMAIL: ${{ secrets.NOTIFICATION_EMAIL }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}

      - name: Commit & push state changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add state/
          git diff --cached --quiet || git commit -m "sync: update playlist state $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          git push
```

---

## 8. GCP Secret Manager キー設計

| シークレット名 | 内容 | 更新方法 |
|---|---|---|
| `spotify-refresh-token` | Spotify OAuth リフレッシュトークン | 初回手動設定、以降は自動更新 |
| `apple-music-cookie` | Apple Music セッションCookie (JSON) | `tools/refresh_cookie.py` で半自動更新 |
| `amazon-music-cookie` | Amazon Music セッションCookie (JSON) | `tools/refresh_cookie.py` で半自動更新 |
| `gmail-app-password` | Gmail アプリパスワード | 手動設定（ほぼ不変） |

---

## 9. Cookie半自動更新ツール設計

### 9.1 フロー

```
1. python tools/refresh_cookie.py --service amazon_music
2. Playwright で Chromium を起動（ヘッドフルモード）
3. Amazon Music ログインページを開く
4. ユーザーが手動でログイン操作を完了
5. ログイン成功を検知（URL遷移 or 特定要素の出現で判定）
6. ブラウザコンテキストから全Cookieを抽出
7. JSON形式でシリアライズ
8. GCP Secret Manager の該当シークレットを新しいバージョンで更新
9. 更新完了を表示してブラウザを閉じる
```

### 9.2 CLI インターフェース

```bash
python tools/refresh_cookie.py --service amazon_music
python tools/refresh_cookie.py --service apple_music
python tools/refresh_cookie.py --service all        # 両方を順番に更新
```

---

## 10. エラーハンドリング方針

| エラー種別 | 対応 |
|---|---|
| 認証エラー (401/403) | ジョブ即時終了 + メール通知 |
| レート制限 (429) | 指数バックオフでリトライ（最大3回） |
| ネットワークエラー | リトライ（最大3回）後、失敗ならメール通知 |
| スクレイピング要素未検出 | 該当サービスの同期をスキップ + メール通知 |
| ISRCマッチ失敗 | `unmatched` に記録、他の曲の同期は続行 |
| Gitプッシュ失敗 | ジョブをエラー終了（次回再実行で回復可能） |

### 10.1 通知メールフォーマット

```
件名: [Music Sync] エラー検知 - {日時}

以下のエラーが発生しました:

■ 認証エラー
  - Amazon Music: Cookie期限切れ (HTTP 401)
    → tools/refresh_cookie.py --service amazon_music を実行してください

■ 未同期楽曲 (2曲)
  - "Rare Song" by Indie Artist → apple_music, amazon_music で見つかりません
  - "Limited Track" by Artist B → amazon_music で見つかりません
```

---

## 11. Playwrightセレクタ管理

Apple Music / Amazon Music のUI変更に備え、スクレイピング用セレクタを外部設定化する。

### 11.1 セレクタ定義ファイル (`config/selectors.yaml`)

```yaml
apple_music:
  login_url: "https://music.apple.com/login"
  logged_in_indicator: "[data-testid='user-menu']"
  playlist_track_row: ".songs-list-row"
  track_title: ".songs-list-row__song-name"
  track_artist: ".songs-list-row__by-line"
  search_input: "input[type='search']"
  search_result_row: ".search-result-row"
  add_to_playlist_button: "[data-testid='add-to-playlist']"

amazon_music:
  login_url: "https://music.amazon.co.jp"
  logged_in_indicator: "#navbarMusicTitle"
  playlist_track_row: ".trackRow"
  track_title: ".trackTitle"
  track_artist: ".trackArtist"
  search_input: "#searchInput"
  search_result_row: ".searchResultRow"
  add_to_playlist_button: ".addToPlaylistButton"
```

UI変更時はこのファイルだけを修正すれば、Python側のコード変更は不要。
