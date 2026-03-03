# Music Playlist Hub - タスク一覧

> 凡例: `[ ]` 未着手 / `[x]` 完了

---

## Phase 1: 基盤構築

### 1.1 プロジェクト初期化

- [x] Git リポジトリ初期化、`.gitignore` 作成（Python テンプレート + `state/` 以外の機密ファイル）
- [x] `requirements.txt` 作成（spotipy, playwright, google-cloud-secret-manager, pyyaml, pytest）
- [x] ディレクトリ構成をスキャフォールド（`src/`, `src/providers/`, `src/utils/`, `config/`, `state/`, `tools/`, `tests/`）

### 1.2 データモデル (`src/models.py`)

- [x] `Track` dataclass 定義（isrc, title, artist, album, service_ids, added_at）
- [x] `PlaylistConfig` dataclass 定義（name, spotify, apple_music, amazon_music の ID/URL）
- [x] `SyncResult` dataclass 定義（added, removed, unmatched, errors）
- [x] `PlaylistInfo` dataclass 定義（name, service_ids）— 自動発見用
- [x] `SyncConfig` dataclass 定義（auto_discover, playlists）— 設定全体

### 1.3 設定ファイルローダー (`src/config_loader.py`)

- [x] `config/playlists.yaml` のパース処理
- [x] バリデーション（必須フィールドの存在チェック、重複プレイリスト名の検知）
- [x] `config/playlists.yaml` のサンプルファイル作成
- [x] `load_config()` 追加（`auto_discover` フラグを含む `SyncConfig` を返す）
- [x] テスト (`tests/test_config_loader.py`)

### 1.4 GCP Secret Manager 連携 (`src/utils/secret_manager.py`)

- [x] シークレット取得関数 `get_secret(secret_id) -> str`
- [x] シークレット更新関数 `set_secret(secret_id, value) -> None`（Cookie更新ツール用）
- [x] GCP プロジェクト ID の環境変数読み込み
- [x] テスト（モック使用）

### 1.5 プロバイダー基底クラス (`src/providers/base.py`)

- [x] `MusicProvider` ABC 定義（authenticate, get_playlist_tracks, add_tracks, remove_tracks, search_track）
- [x] `get_all_playlists()`, `create_playlist()` 抽象メソッド追加
- [x] `AuthenticationError` カスタム例外定義

---

## Phase 2: Spotify 同期の完成

### 2.1 Spotify プロバイダー (`src/providers/spotify.py`)

- [x] `SpotifyProvider(MusicProvider)` クラスのスケルトン作成
- [x] `authenticate()`: Secret Manager からリフレッシュトークン取得 → spotipy クライアント初期化
- [x] `get_playlist_tracks()`: プレイリスト全曲取得 → `Track` リストに変換（ISRC, added_at 含む）
- [x] `add_tracks()`: プレイリストへ楽曲追加（Spotify URI 指定）
- [x] `remove_tracks()`: プレイリストから楽曲削除
- [x] `search_track()`: ISRC 検索 → フォールバックで曲名+アーティスト検索
- [x] `get_all_playlists()`: ユーザーの全プレイリスト取得（ページネーション対応）
- [x] `create_playlist()`: 新規プレイリスト作成
- [x] テスト (`tests/test_providers/test_spotify.py`)

### 2.2 ISRC マッチング (`src/utils/isrc.py`)

- [x] `match_by_isrc(track, provider) -> Track | None`: ISRC でサービス内楽曲を検索
- [x] `match_by_metadata(track, provider) -> Track | None`: 曲名+アーティスト名でフォールバック検索
- [x] `find_match(track, provider) -> Track | None`: 上記を順に試行する統合関数
- [x] テスト (`tests/test_isrc.py`)

### 2.3 差分検知エンジン (`src/sync_engine.py`)

- [x] `load_state(playlist_name) -> dict`: `state/{name}.json` の読み込み（初回は空状態を返す）
- [x] `save_state(playlist_name, state) -> None`: 状態ファイルの書き出し
- [x] `compute_diff(previous, current) -> (added, removed)`: ISRC ベースで差分計算
- [x] `resolve_conflicts(diffs_by_service) -> (to_add, to_remove)`: タイムスタンプ優先の競合解決
- [x] `sync_playlist(playlist_config, providers) -> SyncResult`: 1プレイリストの同期全体を実行
- [x] テスト (`tests/test_sync_engine.py`)

### 2.4 エントリーポイント (`src/main.py`)

- [x] 設定読み込み → プロバイダー初期化 → 全プレイリスト同期のオーケストレーション
- [x] 自動発見パイプライン統合（`auto_discover: true` 時に実行、失敗時は手動設定にフォールバック）
- [x] logging 設定（INFO/WARNING/ERROR）
- [x] 終了コード管理（エラー時は非ゼロで終了）

### 2.5 GitHub Actions 初期構築

- [x] `.github/workflows/sync.yml` 作成（Python セットアップ、依存インストール、GCP 認証、同期実行、state コミット）
- [x] `workflow_dispatch` で手動実行可能にする
- [x] Spotify のみで E2E 動作確認

---

## Phase 3: Apple Music / Amazon Music 連携

### 3.1 Playwright 共通基盤

- [x] Cookie 注入によるログイン状態復元のヘルパー関数
- [x] `config/selectors.yaml` のローダー実装
- [x] ブラウザ起動・終了のコンテキストマネージャー（タイムアウト 30秒/操作）

### 3.2 Apple Music プロバイダー (`src/providers/apple_music.py`)

- [x] `AppleMusicProvider(MusicProvider)` クラスのスケルトン作成
- [x] `authenticate()`: Secret Manager から Cookie 取得 → Playwright セッションに注入
- [x] `get_playlist_tracks()`: プレイリストページをスクレイピングして曲目取得
- [x] `add_tracks()`: 検索 → プレイリストに追加のブラウザ操作
- [x] `remove_tracks()`: プレイリストから削除のブラウザ操作
- [x] `search_track()`: Apple Music 検索を利用したフォールバック
- [x] ISRC 取得方法の調査・実装
- [x] `get_all_playlists()`: ライブラリページからプレイリスト一覧取得
- [x] `create_playlist()`: ブラウザ操作でプレイリスト作成
- [x] テスト (`tests/test_providers/test_apple_music.py`)

### 3.3 Amazon Music プロバイダー (`src/providers/amazon_music.py`)

- [x] `AmazonMusicProvider(MusicProvider)` クラスのスケルトン作成
- [x] `authenticate()`: Secret Manager から Cookie 取得 → Playwright セッションに注入
- [x] `get_playlist_tracks()`: プレイリストページをスクレイピングして曲目取得
- [x] `add_tracks()`: 検索 → プレイリストに追加のブラウザ操作
- [x] `remove_tracks()`: プレイリストから削除のブラウザ操作
- [x] `search_track()`: Amazon Music 検索を利用したフォールバック
- [x] ISRC 取得方法の調査・実装（ASIN 経由含む）
- [x] `get_all_playlists()`: ライブラリページからプレイリスト一覧取得
- [x] `create_playlist()`: ブラウザ操作でプレイリスト作成
- [x] テスト (`tests/test_providers/test_amazon_music.py`)

### 3.4 3サービス間同期の統合テスト

- [x] 全プロバイダーを組み合わせた同期の E2E 動作確認
- [x] 競合解決の実動作確認（追加+削除の同時発生ケース）
- [x] unmatched 楽曲の記録が正しく行われるか確認

---

## Phase 4: 運用機能

### 4.1 メール通知 (`src/notification.py`)

- [x] Gmail SMTP 接続（アプリパスワード使用）
- [x] エラー通知メールの組み立て（認証エラー、未同期楽曲のサマリー）
- [x] `main.py` からの呼び出し（エラー/unmatched がある場合のみ送信）
- [x] テスト（SMTP モック使用）

### 4.2 エラーハンドリング強化

- [x] 認証エラー (401/403) → 即時終了 + 通知
- [x] レート制限 (429) → 指数バックオフリトライ（最大3回）
- [x] ネットワークエラー → リトライ（最大3回）
- [x] スクレイピング要素未検出 → 該当サービスをスキップ + 通知
- [x] 部分失敗時の継続動作（1サービスの失敗で全体を止めない）

### 4.3 Cookie 半自動更新ツール (`tools/refresh_cookie.py`)

- [x] CLI 引数パース（`--service amazon_music|apple_music|all`）
- [x] Playwright ヘッドフルモードでログインページを開く
- [x] ログイン完了の検知（URL 遷移 or 特定要素の出現）
- [x] Cookie 抽出 → JSON シリアライズ → Secret Manager へアップロード
- [x] 完了メッセージ表示

### 4.4 GitHub Actions 本番設定

- [x] Cron スケジュール有効化（毎日 AM3:00 UTC）
- [x] Playwright ブラウザインストールステップ追加
- [x] タイムアウト設定（ジョブ全体 10分）
- → 残りのシークレット登録・安定稼働確認は Phase 6 に移動

---

## Phase 5: 全プレイリスト自動同期

### 5.1 自動発見モジュール (`src/discovery.py`)

- [x] `normalize_name()`: プレイリスト名の正規化（NFKC + 小文字化）
- [x] `collect_all_playlists()`: 全プロバイダーからプレイリスト一覧取得
- [x] `match_playlists_by_name()`: 名前ベースでクロスサービスマッチング
- [x] `create_missing_playlists()`: 存在しないサービスにプレイリスト自動作成
- [x] `merge_with_manual()`: 手動設定（playlists.yaml）との統合（手動が優先）
- [x] `discover_and_merge_playlists()`: 上記を統合したメインパイプライン
- [x] 発見結果を `state/discovery_cache.json` にキャッシュ
- [x] テスト (`tests/test_discovery.py` — 19テスト)

### 5.2 設定・統合

- [x] `config/playlists.yaml` に `auto_discover: true` 追加
- [x] `config/selectors.yaml` にライブラリページ用・プレイリスト作成用セレクター追加
- [x] 統合テスト更新（`load_config` 対応）

---

## Phase 6: デプロイ・安定稼働

### 6.1 セレクター実地検証

- [x] セレクター検証ツール作成（`tools/verify_selectors.py`）— `--suggest` モードで代替候補提案機能付き
- [x] `config/selectors.yaml` をフォールバック付きカンマ区切りセレクタに更新（両サービス対応）
- [x] Apple Music ライブラリページのセレクター検証・修正（`python tools/verify_selectors.py --service apple_music --suggest --no-headless`）
- [x] Apple Music プレイリスト作成のセレクター検証・修正 — Web 版非対応のため `create_playlist()` を ScrapingError 送出に変更
- [x] Amazon Music ライブラリページのセレクター検証・修正（`python tools/verify_selectors.py --service amazon_music --suggest --no-headless`）
- [x] Amazon Music プレイリスト作成のセレクター検証・修正 — セレクター検証 OK（Web Components: `music-button[icon-name='add']`）
- [x] `--dry-run` で自動発見パイプラインの動作確認済み（Amazon 16PL 発見、Apple 3PL サイドバーフォールバック）
- [ ] `workflow_dispatch` で手動実行し、本番動作確認

### 6.2 GitHub Secrets 登録確認

- [x] シークレット検証ツール作成（`tools/verify_secrets.py`）
- [x] `GCP_SA_KEY`（サービスアカウントキー JSON）— 登録済み（SA: `music-sync@music-playlist-hub.iam.gserviceaccount.com`）
- [x] `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — 登録済み
- [x] `NOTIFICATION_EMAIL` / `GMAIL_APP_PASSWORD` — 登録済み（`kabuyuu0913@gmail.com`）
- [x] GCP Secret Manager 側: `spotify-refresh-token`(v1), `apple-music-cookie`(v2), `amazon-music-cookie`(v2) — 全て enabled

### 6.3 GitHub Actions タイムアウト見直し

- [x] タイムアウトを10分→20分に拡大（`.github/workflows/sync.yml`）

### 6.4 安定稼働確認

- [x] `--dry-run` モード追加（`src/main.py`）— 認証・発見・差分計算のみ実行し、実際の変更をスキップ
- [x] `--verbose` フラグ追加（`src/main.py`）— DEBUG レベルログでトラブルシュート支援
- [ ] cron 自動実行を数日間モニタリング
- [ ] エラー通知メールが正しく届くか確認
- [ ] state/ の差分が正しく git commit されるか確認

---

## 残タスク（手動作業が必要）

> 以下はすべて実環境での操作・確認が必要なタスクです。
> コードで自動化できる範囲は Phase 6 の `[x]` タスクで完了済みです。

### 推奨実施手順

```bash
# 1. シークレットの登録状況を確認
python tools/verify_secrets.py

# 2. 不足分を GitHub Settings / GCP Console で登録

# 3. セレクターを実サイトで検証（Cookie 設定後）
python tools/verify_selectors.py --service all --suggest --no-headless

# 4. NG セレクターを config/selectors.yaml に反映

# 5. dry-run でパイプライン全体をテスト
python -m src.main --dry-run -v

# 6. GitHub Actions の workflow_dispatch で本番実行

# 7. 数日間 cron 実行をモニタリング
```

---

## 並列実行プラン

タスク間の依存関係を分析し、ファイル競合が発生しない単位で Wave に分割する。
各 Wave 内のタスクは独立した Agent に割り当てて同時実行可能。

### 依存関係

```
1.1
 ├── 1.2 models.py
 │    ├── 1.3 config_loader.py
 │    ├── 1.5 base.py
 │    │    ├── 2.1 Spotify Provider ←─ 1.4
 │    │    ├── 2.2 ISRC マッチング
 │    │    └── 3.1 Playwright基盤 ←── 1.4
 │    │         ├── 3.2 Apple Music ──┐
 │    │         ├── 3.3 Amazon Music ─┤
 │    │         └── 4.3 Cookie Tool ←─┘─ 1.4
 │    ├── 2.3 sync_engine（コア）
 │    │    └── 2.3 sync_playlist() ←─ 2.1, 2.2
 │    │         └── 2.4 main.py ←──── 1.3, 4.1
 │    │              └── 2.5 Actions
 │    └── 4.1 notification.py
 │
 └── 1.4 secret_manager.py ※ 1.2 と並列可
```

### Wave 一覧

#### Wave 1: 初期化（直列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| - | **1.1** プロジェクト初期化 | .gitignore, requirements.txt, ディレクトリ |

#### Wave 2: 基盤（2並列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| A | **1.2** データモデル | `src/models.py` |
| B | **1.4** Secret Manager | `src/utils/secret_manager.py` |

> 1.4 は models.py に依存しないため並列可。

#### Wave 3: インターフェース層（3並列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| A | **1.5** プロバイダー基底クラス | `src/providers/base.py` |
| B | **1.3** 設定ファイルローダー | `src/config_loader.py`, `config/playlists.yaml` |
| C | **4.1** メール通知 | `src/notification.py` |

> 全て別ファイル。1.3 は PlaylistConfig を、4.1 は SyncResult を import するのみ。

#### Wave 4: コアロジック（3〜4並列） ← 最大の並列ポイント

| Agent | タスク | 対象ファイル |
|---|---|---|
| A | **2.1** Spotify Provider | `src/providers/spotify.py` |
| B | **2.2** ISRC マッチング | `src/utils/isrc.py` |
| C | **2.3** 差分検知エンジン（コア部分: load/save/diff/conflict） | `src/sync_engine.py` |
| D | **3.1** Playwright 共通基盤（任意） | `src/providers/` 内ヘルパー, `config/selectors.yaml` |

> 全て別ファイルで互いに依存なし。3.1 は Phase 3 だが前倒し可能。

#### Wave 5: スクレイピング（3並列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| A | **3.2** Apple Music Provider | `src/providers/apple_music.py` |
| B | **3.3** Amazon Music Provider | `src/providers/amazon_music.py` |
| C | **4.3** Cookie 更新ツール | `tools/refresh_cookie.py` |

> 3.2 と 3.3 は同じ 3.1 基盤を利用するが、編集ファイルは完全に別。

#### Wave 6: 統合（直列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| - | **2.3** sync_playlist() 統合関数追加 | `src/sync_engine.py` |
| - | **2.4** エントリーポイント | `src/main.py` |
| - | **2.5** GitHub Actions 初期構築 | `.github/workflows/sync.yml` |

> 2.4 は 1.3, 2.1, 2.2, 2.3, 4.1 全ての完成が前提。

#### Wave 7: 仕上げ（2並列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| A | **3.4** 統合テスト | `tests/` |
| B | **4.2** エラーハンドリング強化 | 各 provider, sync_engine 等 |

#### Wave 8: 最終（直列）

| Agent | タスク | 対象ファイル |
|---|---|---|
| - | **4.4** GitHub Actions 本番設定 | `.github/workflows/sync.yml` |
