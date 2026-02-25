#!/usr/bin/env python3
"""Secrets verification tool for Phase 6.2 deployment readiness.

Checks that all required secrets are configured in both
GitHub repository secrets and GCP Secret Manager.

Usage:
    python tools/verify_secrets.py
    python tools/verify_secrets.py --github-only
    python tools/verify_secrets.py --gcp-only
    python tools/verify_secrets.py --repo owner/repo
    python -m tools.verify_secrets
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Allow imports from project root when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_GITHUB_SECRETS: list[str] = [
    "GCP_SA_KEY",
    "GCP_PROJECT_ID",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "NOTIFICATION_EMAIL",
    "GMAIL_APP_PASSWORD",
]

REQUIRED_GCP_SECRETS: list[str] = [
    "spotify-refresh-token",
    "apple-music-cookie",
    "amazon-music-cookie",
]

# ---------------------------------------------------------------------------
# GitHub secrets check
# ---------------------------------------------------------------------------


def _detect_repo_from_git() -> str | None:
    """Detect the owner/repo from the git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    # Handle SSH: git@github.com:owner/repo.git
    if url.startswith("git@github.com:"):
        path = url.removeprefix("git@github.com:").removesuffix(".git")
        return path

    # Handle HTTPS: https://github.com/owner/repo.git
    if "github.com/" in url:
        path = url.split("github.com/", 1)[1].removesuffix(".git")
        return path

    return None


def check_github_secrets(repo: str | None = None) -> tuple[list[str], list[str]]:
    """Check GitHub repository secrets via ``gh secret list``.

    Returns:
        (found, missing) lists of secret names.
    """
    if repo is None:
        repo = _detect_repo_from_git()

    cmd = ["gh", "secret", "list"]
    if repo:
        cmd += ["--repo", repo]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        print("  ERROR: GitHub CLI (gh) is not installed or not in PATH.")
        return [], list(REQUIRED_GITHUB_SECRETS)
    except subprocess.CalledProcessError as exc:
        print(f"  ERROR: `gh secret list` failed (exit {exc.returncode}):")
        err = exc.stderr.strip() if exc.stderr else "(no output)"
        print(f"    {err}")
        return [], list(REQUIRED_GITHUB_SECRETS)

    # Parse output: each line starts with the secret name followed by whitespace
    configured: set[str] = set()
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if parts:
            configured.add(parts[0])

    found = [s for s in REQUIRED_GITHUB_SECRETS if s in configured]
    missing = [s for s in REQUIRED_GITHUB_SECRETS if s not in configured]
    return found, missing


# ---------------------------------------------------------------------------
# GCP Secret Manager check
# ---------------------------------------------------------------------------


def check_gcp_secrets() -> tuple[list[tuple[str, str]], list[str]]:
    """Check GCP Secret Manager secrets.

    Returns:
        (found, missing) where *found* is a list of
        ``(secret_id, info_str)`` tuples and *missing* is a list of
        secret IDs that were not found.
    """
    try:
        from google.cloud import secretmanager  # noqa: F401
    except ImportError:
        print("  ERROR: google-cloud-secret-manager is not installed.")
        return [], list(REQUIRED_GCP_SECRETS)

    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        print("  ERROR: GCP_PROJECT_ID environment variable is not set.")
        return [], list(REQUIRED_GCP_SECRETS)

    try:
        client = secretmanager.SecretManagerServiceClient()
    except Exception as exc:
        print(f"  ERROR: Could not create Secret Manager client: {exc}")
        return [], list(REQUIRED_GCP_SECRETS)

    found: list[tuple[str, str]] = []
    missing: list[str] = []

    for secret_id in REQUIRED_GCP_SECRETS:
        secret_name = f"projects/{project_id}/secrets/{secret_id}"
        try:
            # List versions to confirm the secret exists and get latest info
            versions = client.list_secret_versions(
                request={"parent": secret_name}
            )
            latest_version = None
            for version in versions:
                if version.state.name == "ENABLED":
                    latest_version = version
                    break  # first enabled version is the most recent

            if latest_version and latest_version.create_time:
                ts = latest_version.create_time.strftime("%Y-%m-%d")
                info = f"exists, last version: {ts}"
            else:
                info = "exists"
            found.append((secret_id, info))
        except Exception:
            missing.append(secret_id)

    return found, missing


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(
    *,
    github_found: list[str] | None = None,
    github_missing: list[str] | None = None,
    gcp_found: list[tuple[str, str]] | None = None,
    gcp_missing: list[str] | None = None,
) -> int:
    """Print a human-readable report and return the exit code (0 or 1)."""
    total = 0
    configured = 0

    if github_found is not None or github_missing is not None:
        gf = github_found or []
        gm = github_missing or []
        print("\n=== GitHub Repository Secrets ===")
        for name in gf:
            print(f"  [OK] {name}")
        for name in gm:
            print(f"  [MISSING] {name} (NOT FOUND)")
        total += len(gf) + len(gm)
        configured += len(gf)

    if gcp_found is not None or gcp_missing is not None:
        gcf = gcp_found or []
        gcm = gcp_missing or []
        print("\n=== GCP Secret Manager ===")
        for name, info in gcf:
            print(f"  [OK] {name} ({info})")
        for name in gcm:
            print(f"  [MISSING] {name} (NOT FOUND)")
        total += len(gcf) + len(gcm)
        configured += len(gcf)

    all_ok = configured == total
    status = "All secrets configured." if all_ok else f"{total - configured} missing."
    print(f"\nSummary: {configured}/{total} secrets configured. {status}")

    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that required secrets are configured in GitHub and GCP.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--github-only",
        action="store_true",
        help="Only check GitHub repository secrets",
    )
    group.add_argument(
        "--gcp-only",
        action="store_true",
        help="Only check GCP Secret Manager secrets",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="GitHub repo in owner/repo format (auto-detected from git remote if omitted)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    check_github = not args.gcp_only
    check_gcp = not args.github_only

    github_found: list[str] | None = None
    github_missing: list[str] | None = None
    gcp_found: list[tuple[str, str]] | None = None
    gcp_missing: list[str] | None = None

    if check_github:
        github_found, github_missing = check_github_secrets(repo=args.repo)

    if check_gcp:
        gcp_found, gcp_missing = check_gcp_secrets()

    exit_code = print_report(
        github_found=github_found,
        github_missing=github_missing,
        gcp_found=gcp_found,
        gcp_missing=gcp_missing,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
