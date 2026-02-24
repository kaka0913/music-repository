from __future__ import annotations

import os

from google.cloud import secretmanager

_client: secretmanager.SecretManagerServiceClient | None = None


def _get_client() -> secretmanager.SecretManagerServiceClient:
    """クライアントをシングルトンで返す"""
    global _client
    if _client is None:
        _client = secretmanager.SecretManagerServiceClient()
    return _client


def _get_project_id() -> str:
    """環境変数 GCP_PROJECT_ID からプロジェクトIDを取得"""
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        raise EnvironmentError("GCP_PROJECT_ID environment variable is not set")
    return project_id


def get_secret(secret_id: str) -> str:
    """Secret Manager からシークレットの最新バージョンを取得する"""
    client = _get_client()
    project_id = _get_project_id()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def set_secret(secret_id: str, value: str) -> None:
    """Secret Manager のシークレットに新しいバージョンを追加する（Cookie更新ツール用）"""
    client = _get_client()
    project_id = _get_project_id()
    parent = f"projects/{project_id}/secrets/{secret_id}"
    client.add_secret_version(
        request={"parent": parent, "payload": {"data": value.encode("utf-8")}}
    )
