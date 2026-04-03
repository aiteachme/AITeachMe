"""存储抽象工厂。

通过 ``get_artifact_store()`` 获取当前运行模式对应的 ArtifactStore 实例。
"""

from __future__ import annotations

from app.shared.infra.storage.base import ArtifactStore
from app.shared.infra.storage.sync_bridge import run_store_sync

_store: ArtifactStore | None = None


def get_artifact_store() -> ArtifactStore:
    """返回全局单例 ArtifactStore。"""

    global _store
    if _store is not None:
        return _store

    from app.shared.infra.config import get_settings

    settings = get_settings()
    if settings.storage_is_s3:
        from app.shared.infra.storage.s3_store import S3ArtifactStore

        _store = S3ArtifactStore(settings)
    else:
        from app.shared.infra.storage.local_store import LocalArtifactStore

        _store = LocalArtifactStore()

    return _store


def reset_artifact_store() -> None:
    """重置全局单例（测试用）。"""

    global _store
    _store = None


__all__ = ["ArtifactStore", "get_artifact_store", "reset_artifact_store", "run_store_sync"]
