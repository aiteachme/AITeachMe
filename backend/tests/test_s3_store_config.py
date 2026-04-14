from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.shared.infra.storage.config import (
    resolve_dogecloud_api_access_key,
    resolve_dogecloud_api_secret_key,
    resolve_dogecloud_space_name,
    resolve_s3_addressing_style,
    resolve_s3_credential_mode,
    s3_uses_dogecloud_tmp_token,
)
from app.shared.infra.storage.s3_store import S3ArtifactStore


def _build_fake_boto_client() -> MagicMock:
    client = MagicMock()
    client.exceptions = SimpleNamespace(NoSuchKey=KeyError)
    return client


def _build_fake_urlopen(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    context_manager = MagicMock()
    context_manager.__enter__.return_value = response
    context_manager.__exit__.return_value = False
    return context_manager


def test_settings_default_s3_addressing_style_is_virtual(monkeypatch) -> None:
    monkeypatch.delenv("S3_ADDRESSING_STYLE", raising=False)
    assert resolve_s3_addressing_style() == "virtual"


def test_settings_respect_explicit_s3_addressing_style(monkeypatch) -> None:
    monkeypatch.setenv("S3_ADDRESSING_STYLE", "path")
    assert resolve_s3_addressing_style() == "path"


def test_settings_fallback_to_virtual_for_invalid_s3_addressing_style(monkeypatch) -> None:
    monkeypatch.setenv("S3_ADDRESSING_STYLE", "invalid")
    assert resolve_s3_addressing_style() == "virtual"


def test_settings_auto_detect_dogecloud_tmp_token_mode(monkeypatch) -> None:
    monkeypatch.setenv("DOGECLOUD_API_ACCESS_KEY", "doge-ak")
    monkeypatch.setenv("DOGECLOUD_API_SECRET_KEY", "doge-sk")

    assert resolve_s3_credential_mode() == "dogecloud_tmp_token"
    assert s3_uses_dogecloud_tmp_token() is True


def test_settings_reuse_s3_keys_for_dogecloud_api_when_explicit_mode_enabled(monkeypatch) -> None:
    monkeypatch.setenv("S3_CREDENTIAL_MODE", "dogecloud_tmp_token")
    monkeypatch.setenv("S3_ACCESS_KEY", "doge-ak")
    monkeypatch.setenv("S3_SECRET_KEY", "doge-sk")
    monkeypatch.delenv("DOGECLOUD_API_ACCESS_KEY", raising=False)
    monkeypatch.delenv("DOGECLOUD_API_SECRET_KEY", raising=False)

    assert resolve_dogecloud_api_access_key() == "doge-ak"
    assert resolve_dogecloud_api_secret_key() == "doge-sk"


def test_settings_prefer_explicit_dogecloud_space_name(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "underlying-s3-bucket")
    monkeypatch.setenv("DOGECLOUD_SPACE_NAME", "my-space-name")

    assert resolve_dogecloud_space_name() == "my-space-name"


def test_s3_artifact_store_passes_addressing_style_and_session_token_to_boto_client(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "demo-bucket")
    monkeypatch.setenv("S3_ENDPOINT", "https://cos.ap-shanghai.myqcloud.com")
    monkeypatch.setenv("S3_ACCESS_KEY", "demo-ak")
    monkeypatch.setenv("S3_SECRET_KEY", "demo-sk")
    monkeypatch.setenv("S3_SESSION_TOKEN", "demo-session-token")
    monkeypatch.setenv("S3_REGION", "ap-shanghai")
    monkeypatch.setenv("S3_ADDRESSING_STYLE", "virtual")
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://cdn.example.com")

    captured_kwargs: dict[str, object] = {}

    def _fake_client(*args, **kwargs):
        del args
        captured_kwargs.update(kwargs)
        return _build_fake_boto_client()

    with patch("app.shared.infra.storage.s3_store.boto3.client", side_effect=_fake_client):
        S3ArtifactStore()

    assert captured_kwargs["endpoint_url"] == "https://cos.ap-shanghai.myqcloud.com"
    assert captured_kwargs["region_name"] == "ap-shanghai"
    assert captured_kwargs["aws_session_token"] == "demo-session-token"
    assert captured_kwargs["config"].s3["addressing_style"] == "virtual"


def test_s3_artifact_store_fetches_dogecloud_tmp_credentials_before_initializing_boto_client(
    monkeypatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET", "underlying-s3-bucket")
    monkeypatch.setenv("S3_ENDPOINT", "https://placeholder.invalid")
    monkeypatch.setenv("S3_ACCESS_KEY", "doge-ak")
    monkeypatch.setenv("S3_SECRET_KEY", "doge-sk")
    monkeypatch.setenv("S3_REGION", "ap-shanghai")
    monkeypatch.setenv("S3_CREDENTIAL_MODE", "dogecloud_tmp_token")
    monkeypatch.setenv("DOGECLOUD_SPACE_NAME", "demo-space")
    monkeypatch.setenv("DOGECLOUD_TMP_TOKEN_CHANNEL", "OSS_FULL")
    monkeypatch.setenv("DOGECLOUD_TMP_TOKEN_SCOPE", "*")
    captured_kwargs: dict[str, object] = {}
    payload = {
        "code": 200,
        "data": {
            "Credentials": {
                "accessKeyId": "tmp-ak",
                "secretAccessKey": "tmp-sk",
                "sessionToken": "tmp-token",
                "expiration": "2030-01-01T00:00:00Z",
            },
            "Buckets": [
                {
                    "s3Bucket": "resolved-bucket",
                    "s3Endpoint": "https://cos.ap-shanghai.myqcloud.com",
                }
            ],
        },
    }

    def _fake_client(*args, **kwargs):
        del args
        captured_kwargs.update(kwargs)
        return _build_fake_boto_client()

    with patch("app.shared.infra.storage.s3_store.urlopen", return_value=_build_fake_urlopen(payload)) as mock_urlopen:
        with patch("app.shared.infra.storage.s3_store.boto3.client", side_effect=_fake_client):
            S3ArtifactStore()

    request = mock_urlopen.call_args.args[0]
    request_body = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.dogecloud.com/auth/tmp_token.json"
    assert request_body == {"channel": "OSS_FULL", "scopes": ["demo-space:*"]}
    assert request.get_header("Authorization", "").startswith("TOKEN doge-ak:")

    assert captured_kwargs["endpoint_url"] == "https://cos.ap-shanghai.myqcloud.com"
    assert captured_kwargs["aws_access_key_id"] == "tmp-ak"
    assert captured_kwargs["aws_secret_access_key"] == "tmp-sk"
    assert captured_kwargs["aws_session_token"] == "tmp-token"
