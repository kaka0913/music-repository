from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.utils import secret_manager


class TestGetSecret:
    """get_secret のテスト"""

    @patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project"})
    def test_access_secret_version_called_with_correct_path(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.payload.data = b"my-secret-value"
        mock_client.access_secret_version.return_value = mock_response

        secret_manager._client = mock_client
        try:
            result = secret_manager.get_secret("my-secret")
        finally:
            secret_manager._client = None

        mock_client.access_secret_version.assert_called_once_with(
            request={"name": "projects/test-project/secrets/my-secret/versions/latest"}
        )
        assert result == "my-secret-value"


class TestSetSecret:
    """set_secret のテスト"""

    @patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project"})
    def test_add_secret_version_called_with_correct_path_and_payload(self):
        mock_client = MagicMock()

        secret_manager._client = mock_client
        try:
            secret_manager.set_secret("my-secret", "new-value")
        finally:
            secret_manager._client = None

        mock_client.add_secret_version.assert_called_once_with(
            request={
                "parent": "projects/test-project/secrets/my-secret",
                "payload": {"data": b"new-value"},
            }
        )


class TestGetProjectId:
    """_get_project_id のテスト"""

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_environment_error_when_not_set(self):
        # GCP_PROJECT_ID が既存の環境変数に含まれている可能性を排除
        env_copy = os.environ.copy()
        env_copy.pop("GCP_PROJECT_ID", None)
        with patch.dict(os.environ, env_copy, clear=True):
            with pytest.raises(EnvironmentError, match="GCP_PROJECT_ID environment variable is not set"):
                secret_manager._get_project_id()
