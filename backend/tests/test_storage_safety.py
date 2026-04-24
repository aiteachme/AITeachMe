from __future__ import annotations

import pytest

from app.shared.infra.storage.base import validate_delete_prefix
from app.shared.infra.storage.local_store import LocalArtifactStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_validate_delete_prefix_rejects_root_and_file_like_values() -> None:
    for prefix in ("", ".", "/", "./", "/users/local/", "users/local", "users/../local/"):
        with pytest.raises(ValueError):
            validate_delete_prefix(prefix)


def test_validate_delete_prefix_accepts_directory_like_scope() -> None:
    assert validate_delete_prefix("users/local/subjects/math/") == "users/local/subjects/math/"
    assert validate_delete_prefix("users\\local\\subjects\\math\\") == "users/local/subjects/math/"


@pytest.mark.anyio
async def test_local_delete_prefix_rejects_runtime_root(tmp_path) -> None:
    store = LocalArtifactStore()
    store._root = tmp_path.resolve()
    await store.write_bytes("users/local/subjects/math/file.txt", b"hello")

    with pytest.raises(ValueError):
        await store.delete_prefix("")

    assert await store.exists("users/local/subjects/math/file.txt")


@pytest.mark.anyio
async def test_local_delete_prefix_removes_only_safe_directory_scope(tmp_path) -> None:
    store = LocalArtifactStore()
    store._root = tmp_path.resolve()
    await store.write_bytes("users/local/subjects/math/file.txt", b"math")
    await store.write_bytes("users/local/subjects/physics/file.txt", b"physics")

    deleted = await store.delete_prefix("users/local/subjects/math/")

    assert deleted == 1
    assert not await store.exists("users/local/subjects/math/file.txt")
    assert await store.exists("users/local/subjects/physics/file.txt")
