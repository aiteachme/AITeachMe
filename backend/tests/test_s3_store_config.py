from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.shared.infra.config import Settings
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


def test_settings_default_s3_addressing_style_is_virtual() -> None:
    settings = Settings.model_construct(
        s3_endpoint="https://cos.ap-shanghai.myqcloud.com",
    )

    assert settings.resolved_s3_addressing_style == "virtual"


def test_settings_respect_explicit_s3_addressing_style() -> None:
    settings = Settings.model_construct(
        s3_endpoint="https://cos.ap-shanghai.myqcloud.com",
        s3_addressing_style="path",
    )

    assert settings.resolved_s3_addressing_style == "path"


def test_settings_fallback_to_virtual_for_invalid_s3_addressing_style() -> None:
    settings = Settings.model_construct(
        s3_endpoint="https://cos.ap-shanghai.myqcloud.com",
        s3_addressing_style="invalid",
    )

    assert settings.resolved_s3_addressing_style == "virtual"


def test_settings_auto_detect_dogecloud_tmp_token_mode() -> None:
    settings = Settings.model_construct(
        dogecloud_api_access_key="doge-ak",
        dogecloud_api_secret_key="doge-sk",
    )

    assert settings.resolved_s3_credential_mode == "dogecloud_tmp_token"
    assert settings.s3_uses_dogecloud_tmp_token is True


def test_settings_reuse_s3_keys_for_dogecloud_api_when_explicit_mode_enabled() -> None:
    settings = Settings.model_construct(
        s3_credential_mode="dogecloud_tmp_token",
        s3_access_key="doge-ak",
        s3_secret_key="doge-sk",
    )

    assert settings.resolved_dogecloud_api_access_key == "doge-ak"
    assert settings.resolved_dogecloud_api_secret_key == "doge-sk"


def test_s3_artifact_store_passes_addressing_style_and_session_token_to_boto_client() -> None:
    settings = Settings.model_construct(
        s3_bucket="demo-bucket",
        s3_endpoint="https://cos.ap-shanghai.myqcloud.com",
        s3_access_key="demo-ak",
        s3_secret_key="demo-sk",
        s3_session_token="demo-session-token",
        s3_region="ap-shanghai",
        s3_addressing_style="virtual",
        s3_public_base_url="https://cdn.example.com",
    )

    captured_kwargs: dict[str, object] = {}

    def _fake_client(*args, **kwargs):
        del args
        captured_kwargs.update(kwargs)
        return _build_fake_boto_client()

    with patch("app.shared.infra.storage.s3_store.boto3.client", side_effect=_fake_client):
        S3ArtifactStore(settings)

    assert captured_kwargs["endpoint_url"] == "https://cos.ap-shanghai.myqcloud.com"
    assert captured_kwargs["region_name"] == "ap-shanghai"
    assert captured_kwargs["aws_session_token"] == "demo-session-token"
    assert captured_kwargs["config"].s3["addressing_style"] == "virtual"


def test_s3_artifact_store_fetches_dogecloud_tmp_credentials_before_initializing_boto_client() -> None:
    settings = Settings.model_construct(
        s3_bucket="demo-space",
        s3_endpoint="https://placeholder.invalid",
        s3_access_key="doge-ak",
        s3_secret_key="doge-sk",
        s3_region="ap-shanghai",
        s3_credential_mode="dogecloud_tmp_token",
        dogecloud_tmp_token_channel="OSS_FULL",
        dogecloud_tmp_token_scope="*",
    )
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
            S3ArtifactStore(settings)

    request = mock_urlopen.call_args.args[0]
    request_body = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.dogecloud.com/auth/tmp_token.json"
    assert request_body == {"channel": "OSS_FULL", "scopes": ["demo-space:*"]}
    assert request.get_header("Authorization", "").startswith("TOKEN doge-ak:")

    assert captured_kwargs["endpoint_url"] == "https://cos.ap-shanghai.myqcloud.com"
    assert captured_kwargs["aws_access_key_id"] == "tmp-ak"
    assert captured_kwargs["aws_secret_access_key"] == "tmp-sk"
    assert captured_kwargs["aws_session_token"] == "tmp-token"
