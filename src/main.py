from __future__ import annotations

import argparse
import logging
import os
import sys

from src.config_loader import load_config
from src.discovery import discover_and_merge_playlists
from src.models import SyncResult
from src.notification import notify_if_needed
from src.providers.apple_music import AppleMusicProvider
from src.providers.amazon_music import AmazonMusicProvider
from src.providers.base import AuthenticationError, MusicProvider
from src.providers.spotify import SpotifyProvider
from src.sync_engine import compute_diff, load_state, sync_playlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI引数をパースして返す。"""
    parser = argparse.ArgumentParser(
        description="Music Playlist Hub - Cross-service playlist sync",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run in dry-run mode: authenticate, discover, and compute diffs "
             "without actually adding/removing tracks or sending notifications.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Set log level to DEBUG for verbose output.",
    )
    return parser.parse_args(argv)


def init_providers() -> dict[str, MusicProvider]:
    """利用可能なプロバイダーを初期化して返す。"""
    providers: dict[str, MusicProvider] = {}

    # Spotify
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if client_id and client_secret:
        try:
            spotify = SpotifyProvider(client_id=client_id, client_secret=client_secret)
            spotify.authenticate()
            providers["spotify"] = spotify
            logger.info("Spotify provider initialized")
        except AuthenticationError as e:
            logger.error("Spotify authentication failed: %s", e)

    # Apple Music
    try:
        apple_music = AppleMusicProvider()
        apple_music.authenticate()
        providers["apple_music"] = apple_music
        logger.info("Apple Music provider initialized")
    except AuthenticationError as e:
        logger.error("Apple Music authentication failed: %s", e)

    # Amazon Music
    try:
        amazon_music = AmazonMusicProvider()
        amazon_music.authenticate()
        providers["amazon_music"] = amazon_music
        logger.info("Amazon Music provider initialized")
    except AuthenticationError as e:
        logger.error("Amazon Music authentication failed: %s", e)

    return providers


def _dry_run_playlist(playlist, providers) -> None:
    """Dry-run モード: プレイリストのトラック取得と差分計算のみ行い、実際の変更はしない。"""
    playlist_name = playlist.name

    # サービスごとのプレイリストID/URLマッピング
    service_playlist_ids: dict[str, str] = {}
    if playlist.spotify and "playlist_id" in playlist.spotify:
        service_playlist_ids["spotify"] = playlist.spotify["playlist_id"]
    if playlist.apple_music and "playlist_url" in playlist.apple_music:
        service_playlist_ids["apple_music"] = playlist.apple_music["playlist_url"]
    if playlist.amazon_music and "playlist_url" in playlist.amazon_music:
        service_playlist_ids["amazon_music"] = playlist.amazon_music["playlist_url"]

    # 各サービスからトラック取得
    all_current_tracks = []
    for service_name, playlist_id in service_playlist_ids.items():
        if service_name not in providers:
            logger.debug("DRY RUN: [%s] Skipping %s (provider not available)",
                         playlist_name, service_name)
            continue
        try:
            tracks = providers[service_name].get_playlist_tracks(playlist_id)
            logger.info("DRY RUN: [%s] %s: %d tracks retrieved",
                        playlist_name, service_name, len(tracks))
            all_current_tracks.extend(tracks)
        except Exception as e:
            logger.error("DRY RUN: [%s] %s: Failed to get tracks - %s",
                         playlist_name, service_name, e)

    if not all_current_tracks:
        logger.warning("DRY RUN: [%s] No tracks retrieved from any service", playlist_name)
        return

    # 前回状態との差分を計算
    state = load_state(playlist_name)
    previous_tracks = state.get("tracks", [])
    added, removed = compute_diff(previous_tracks, all_current_tracks)

    logger.info(
        "DRY RUN: Would add %d tracks, remove %d tracks for playlist '%s'",
        len(added), len(removed), playlist_name,
    )

    if added:
        for track in added:
            logger.debug("DRY RUN:   + %s - %s (ISRC: %s)",
                         track.title, track.artist, track.isrc)
    if removed:
        for track in removed:
            if isinstance(track, dict):
                logger.debug("DRY RUN:   - %s - %s (ISRC: %s)",
                             track.get("title", "?"), track.get("artist", "?"),
                             track.get("isrc", "?"))
            else:
                logger.debug("DRY RUN:   - %s - %s (ISRC: %s)",
                             track.title, track.artist, track.isrc)


def main(dry_run: bool = False, verbose: bool = False) -> int:
    """メイン処理。終了コードを返す。"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose mode enabled")

    if dry_run:
        logger.info("=== Music Playlist Hub - DRY RUN Start ===")
    else:
        logger.info("=== Music Playlist Hub - Sync Start ===")

    # 1. 設定読み込み
    try:
        config = load_config()
        logger.info("Loaded config (auto_discover=%s, %d manual playlists)",
                     config.auto_discover, len(config.playlists))
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        return 1

    # 2. プロバイダー初期化
    providers = init_providers()
    if not providers:
        logger.error("No providers available. Exiting.")
        return 1

    logger.info("Active providers: %s", ", ".join(providers.keys()))

    # 3. プレイリスト一覧を決定（自動発見 or 手動設定）
    if config.auto_discover:
        logger.info("Auto-discovery enabled. Discovering playlists...")
        try:
            playlists = discover_and_merge_playlists(providers, config.playlists)
            logger.info("Discovered %d playlists to sync", len(playlists))
        except Exception as e:
            logger.warning("Discovery failed, falling back to manual config: %s", e)
            playlists = config.playlists
    else:
        playlists = config.playlists

    # 4. 全プレイリスト同期（or dry-run）
    results: dict[str, SyncResult] = {}
    has_errors = False

    if dry_run:
        for playlist in playlists:
            logger.info("--- DRY RUN: %s ---", playlist.name)
            try:
                _dry_run_playlist(playlist, providers)
            except Exception as e:
                logger.error("DRY RUN: [%s] Failed: %s", playlist.name, e)

        logger.info("=== Music Playlist Hub - DRY RUN Complete ===")
        return 0

    for playlist in playlists:
        logger.info("--- Syncing: %s ---", playlist.name)
        try:
            result = sync_playlist(playlist, providers)
            results[playlist.name] = result

            if result.errors:
                has_errors = True
                for error in result.errors:
                    logger.error("[%s] %s", playlist.name, error)

            logger.info(
                "[%s] Done: +%d -%d, %d unmatched, %d errors",
                playlist.name,
                len(result.added),
                len(result.removed),
                len(result.unmatched),
                len(result.errors),
            )
        except Exception as e:
            logger.error("[%s] Sync failed: %s", playlist.name, e)
            results[playlist.name] = SyncResult(errors=[str(e)])
            has_errors = True

    # 5. 通知（エラー/unmatched がある場合のみ）
    notification_email = os.environ.get("NOTIFICATION_EMAIL")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if notification_email and gmail_app_password:
        try:
            notify_if_needed(results, notification_email, gmail_app_password)
        except Exception as e:
            logger.error("Failed to send notification: %s", e)

    logger.info("=== Music Playlist Hub - Sync Complete ===")
    return 1 if has_errors else 0


if __name__ == "__main__":
    args = parse_args()
    sys.exit(main(dry_run=args.dry_run, verbose=args.verbose))
