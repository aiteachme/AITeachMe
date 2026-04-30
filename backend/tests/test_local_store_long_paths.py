from __future__ import annotations

import asyncio
from pathlib import Path

from app.shared.infra.runtime.paths import get_runtime_data_dir
from app.shared.infra.storage.local_store import LocalArtifactStore


def test_local_artifact_store_handles_long_asset_paths(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AITEACHME_DATA_DIR", str(data_dir))
    get_runtime_data_dir.cache_clear()

    try:
        store = LocalArtifactStore()
        source = tmp_path / "source.bin"
        source.write_bytes(b"asset-bytes")
        long_key = (
            "users/u/files/"
            + "a" * 90
            + "/assets/"
            + "b" * 170
            + ".jpg"
        )

        assert len(str(data_dir / Path(long_key))) > 260

        asyncio.run(store.write_file(long_key, source))

        assert asyncio.run(store.exists(long_key)) is True
        assert asyncio.run(store.read_bytes(long_key)) == b"asset-bytes"
        assert asyncio.run(store.materialize_to_temp(long_key, tmp_path)).read_bytes() == b"asset-bytes"
        assert long_key in asyncio.run(store.list_prefix("users/u/files/"))
        assert asyncio.run(store.delete_prefix("users/u/files/")) == 1
        assert asyncio.run(store.exists(long_key)) is False
    finally:
        get_runtime_data_dir.cache_clear()
