from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

from app.shared.infra.config import Settings
from app.shared.infra.storage.s3_store import S3ArtifactStore


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


def test_s3_artifact_store_passes_addressing_style_to_boto_client() -> None:
    settings = Settings.model_construct(
        s3_bucket="demo-bucket",
        s3_endpoint="https://cos.ap-shanghai.myqcloud.com",
        s3_access_key="demo-ak",
        s3_secret_key="demo-sk",
        s3_region="ap-shanghai",
        s3_addressing_style="virtual",
        s3_public_base_url="https://cdn.example.com",
    )

    captured_kwargs: dict[str, object] = {}

    fake_boto3 = ModuleType("boto3")

    def _fake_client(*args, **kwargs):
        del args
        captured_kwargs.update(kwargs)
        return object()

    fake_boto3.client = _fake_client  # type: ignore[attr-defined]

    fake_botocore = ModuleType("botocore")
    fake_botocore_config = ModuleType("botocore.config")

    class FakeBotoConfig:
        def __init__(self, **kwargs) -> None:
            self.signature_version = kwargs.get("signature_version")
            self.retries = kwargs.get("retries")
            self.s3 = kwargs.get("s3")

    fake_botocore_config.Config = FakeBotoConfig  # type: ignore[attr-defined]

    with patch.dict(
        sys.modules,
        {
            "boto3": fake_boto3,
            "botocore": fake_botocore,
            "botocore.config": fake_botocore_config,
        },
    ):
        S3ArtifactStore(settings)

    assert captured_kwargs["endpoint_url"] == "https://cos.ap-shanghai.myqcloud.com"
    assert captured_kwargs["region_name"] == "ap-shanghai"
    assert captured_kwargs["config"].s3["addressing_style"] == "virtual"
