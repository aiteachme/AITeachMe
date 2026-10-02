import asyncio
from types import SimpleNamespace

from app.shared.infra.storage import local_store
from app.shared.infra.storage.content_store import ContentStore
from app.shared.infra.storage.s3_store import S3ArtifactStore
from app.workflows.digest.common import asset_indexer
from app.workflows.digest.common.models import SourcePacket


def packet(file_id, image_refs):
    return SourcePacket(
        file_id=file_id, filename=f"{file_id}.md", filetype="md", markdown_path="",
        asset_dir="assets/shared", normalized_content="", char_count=0,
        has_formulas=False, has_tables=False, has_images=bool(image_refs), image_refs=image_refs,
    )


def test_asset_index_uses_listing_metadata_without_reading_image_bodies(monkeypatch):
    listings = []

    async def list_sizes(prefix):
        listings.append(prefix)
        return {"assets/shared/image_p1.png": 10_000_000, "assets/shared/empty.png": 0}

    async def forbid_download(*args, **kwargs):
        raise AssertionError("asset indexing must not download images")

    monkeypatch.setattr(asset_indexer, "get_content_store", lambda: SimpleNamespace(
        list_prefix_sizes=list_sizes, read_bytes=forbid_download,
    ))
    registry = asset_indexer.build_asset_registry("course-assets", [
        packet("first", ["image_p1.png", "image_p1.png", "missing.png"]),
        packet("second", ["empty.png"]), packet("text-only", []),
    ])
    assert listings == ["assets/shared/"]
    assert [asset.file_size for asset in registry.assets] == [10_000_000, 0, 0]
    assert [asset.ocr_available for asset in registry.assets] == [True, False, True]
    assert registry.assets[0].page_number == 1


def test_local_listing_sizes_match_files_without_loading_bodies(monkeypatch, tmp_path):
    monkeypatch.setattr(local_store, "get_runtime_data_dir", lambda: tmp_path)
    store = ContentStore(local_store.LocalArtifactStore())

    async def exercise():
        await store.write_bytes("assets/first.png", b"123")
        await store.write_bytes("assets/nested/second.png", b"12345")
        await store.write_bytes("unrelated.png", b"x")
        assert await store.list_prefix_sizes("assets/") == {
            "assets/first.png": 3, "assets/nested/second.png": 5,
        }
        assert await store.list_prefix_sizes("missing/") == {}

    asyncio.run(exercise())


def test_s3_listing_sizes_preserve_pagination_without_get_requests():
    requests = []

    def list_objects(**kwargs):
        requests.append(kwargs)
        if kwargs.get("ContinuationToken") == "page-2":
            return {"Contents": [{"Key": "assets/b.png", "Size": 20}], "IsTruncated": False}
        return {
            "Contents": [{"Key": "assets/a.png", "Size": 10}],
            "IsTruncated": True, "NextContinuationToken": "page-2",
        }

    client = SimpleNamespace(list_objects_v2=list_objects)
    store = object.__new__(S3ArtifactStore)
    store._bucket = "test-bucket"
    store._call_with_refresh = lambda handler: handler(client)

    async def run_sync(handler, *args):
        return handler(*args)

    store._run_sync = run_sync
    assert asyncio.run(store.list_prefix_sizes("assets/")) == {"assets/a.png": 10, "assets/b.png": 20}
    assert len(requests) == 2
    assert requests[1]["ContinuationToken"] == "page-2"
    assert asyncio.run(store.list_prefix("assets/")) == ["assets/a.png", "assets/b.png"]
