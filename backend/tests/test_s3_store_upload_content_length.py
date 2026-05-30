from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

import boto3
from botocore.stub import ANY, Stubber

from app.shared.infra.storage.s3_store import S3ArtifactStore


class _RecordingS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.upload_file_called = False

    def put_object(self, **kwargs: Any) -> None:
        body = kwargs.get("Body")
        if hasattr(body, "read"):
            kwargs["Body"] = body.read()
        self.put_calls.append(kwargs)

    def upload_file(self, *_args: Any, **_kwargs: Any) -> None:
        self.upload_file_called = True
        raise AssertionError("write_file must not use multipart upload_file")


def _make_store(client: _RecordingS3Client) -> S3ArtifactStore:
    store = object.__new__(S3ArtifactStore)
    store._bucket = "test-bucket"

    async def run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    def call_with_refresh(client_call: Callable[[Any], Any]) -> Any:
        return client_call(client)

    store._run_sync = run_sync  # type: ignore[method-assign]
    store._call_with_refresh = call_with_refresh  # type: ignore[method-assign]
    return store


def test_write_file_uses_single_put_object_with_explicit_content_length(tmp_path: Path) -> None:
    client = _RecordingS3Client()
    store = _make_store(client)
    source = tmp_path / "large.pdf"
    payload = b"x" * (8 * 1024 * 1024 + 1)
    source.write_bytes(payload)

    asyncio.run(store.write_file("users/u/files/file/raw.pdf", source))

    assert client.upload_file_called is False
    assert len(client.put_calls) == 1
    call = client.put_calls[0]
    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == "users/u/files/file/raw.pdf"
    assert call["ContentLength"] == len(payload)
    assert call["Body"] == payload


def test_write_bytes_sets_explicit_content_length() -> None:
    client = _RecordingS3Client()
    store = _make_store(client)
    payload = b"hello"

    asyncio.run(store.write_bytes("users/u/files/file/meta.json", payload))

    assert len(client.put_calls) == 1
    call = client.put_calls[0]
    assert call["ContentLength"] == len(payload)
    assert call["Body"] == payload


def test_write_file_put_object_parameters_match_botocore_model(tmp_path: Path) -> None:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    source = tmp_path / "large.pdf"
    payload = b"x" * (8 * 1024 * 1024 + 1)
    source.write_bytes(payload)

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            {
                "Bucket": "test-bucket",
                "Key": "users/u/files/file/raw.pdf",
                "Body": ANY,
                "ContentLength": len(payload),
            },
        )
        store = _make_store(client)  # type: ignore[arg-type]
        asyncio.run(store.write_file("users/u/files/file/raw.pdf", source))
