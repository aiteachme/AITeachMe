from __future__ import annotations

import asyncio
import base64
import hashlib
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from app.shared.infra.storage import s3_store


pytest.importorskip("boto3")
from botocore.awsrequest import AWSResponse


@pytest.mark.parametrize("refresh_client", [False, True])
def test_delete_prefix_sends_signed_md5_for_serialized_batches(monkeypatch, refresh_client):
    values = {
        "S3_BUCKET": "test-bucket",
        "S3_ENDPOINT": "https://s3.example.invalid",
        "S3_ACCESS_KEY": "test-access-key",
        "S3_SECRET_KEY": "test-secret-key",
    }
    monkeypatch.setattr(s3_store, "get_env", lambda name, default=None: values.get(name, default))
    monkeypatch.setattr(s3_store, "resolve_s3_addressing_style", lambda: "path")
    monkeypatch.setattr(s3_store, "resolve_s3_credential_mode", lambda: "static")
    monkeypatch.setattr(s3_store, "s3_uses_dogecloud_tmp_token", lambda: False)
    store = s3_store.S3ArtifactStore()
    if refresh_client:
        store._refresh_client(force=True)

    prefix = "users/test/courses/course-test/"
    keys = [prefix + f"中文 & <资料>/{index}.md" for index in range(1001)]

    async def list_prefix(requested_prefix):
        assert requested_prefix == prefix
        return keys

    monkeypatch.setattr(store, "list_prefix", list_prefix)
    requests = []

    def respond(request, **kwargs):
        requests.append(request)
        xml = b'<DeleteResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"/>'
        raw = SimpleNamespace(stream=lambda **kwargs: iter([xml]))
        return AWSResponse(request.url, 200, {"content-type": "application/xml"}, raw)

    store._client.meta.events.register("before-send.s3.DeleteObjects", respond)
    try:
        assert asyncio.run(store.delete_prefix(prefix)) == len(keys)
        assert len(requests) == 2
        deleted_keys = []
        for request in requests:
            digest = base64.b64encode(hashlib.md5(request.body, usedforsecurity=False).digest())
            assert request.headers.get("Content-MD5") == digest
            assert b"content-md5" in request.headers["Authorization"]
            payload = ElementTree.fromstring(request.body)
            deleted_keys.extend(element.text for element in payload.findall(".//{*}Key"))
        assert deleted_keys == keys
    finally:
        store._client.close()
