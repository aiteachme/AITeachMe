"""存储抽象工厂。

通过 ``get_artifact_store()`` 获取底层 ArtifactStore 实例。
通过 ``get_content_store()`` 获取上层 ContentStore 实例（业务代码推荐用法）。
"""

from __future__ import annotations

from app.shared.infra.storage.base import ArtifactStore
from app.shared.infra.storage.config import storage_is_s3
from app.shared.infra.storage.content_store import ContentStore
from app.shared.infra.storage.subject_scope import (
    SubjectStorageScope,
    UserFileStorageScope,
    build_file_storage_segment,
    build_subject_storage_scope,
    build_user_file_storage_scope,
    resolve_subject_storage_scope,
    sanitize_storage_file_stem,
)
from app.shared.infra.storage.sync_bridge import run_store_sync

_store: ArtifactStore | None = None
_content_store: ContentStore | None = None


def get_artifact_store() -> ArtifactStore:
    """返回全局单例 ArtifactStore（底层字节接口）。"""

    global _store
    if _store is not None:
        return _store

    if storage_is_s3():
        from app.shared.infra.storage.s3_store import S3ArtifactStore

        _store = S3ArtifactStore()
    else:
        from app.shared.infra.storage.local_store import LocalArtifactStore

        _store = LocalArtifactStore()

    return _store


def get_content_store() -> ContentStore:
    """返回全局单例 ContentStore（业务代码推荐接口）。

    包装 ArtifactStore，提供 key 构建、文本/JSON 读写、工作目录等便捷方法。
    业务代码应优先使用此接口，避免直接检查 is_cloud_mode。
    """

    global _content_store
    if _content_store is not None:
        return _content_store

    _content_store = ContentStore(get_artifact_store())
    return _content_store


def reset_artifact_store() -> None:
    """重置全局单例（测试用）。"""

    global _store, _content_store
    _store = None
    _content_store = None


__all__ = [
    "ArtifactStore",
    "ContentStore",
    "SubjectStorageScope",
    "UserFileStorageScope",
    "build_file_storage_segment",
    "build_subject_storage_scope",
    "build_user_file_storage_scope",
    "get_artifact_store",
    "get_content_store",
    "resolve_subject_storage_scope",
    "reset_artifact_store",
    "run_store_sync",
    "sanitize_storage_file_stem",
]
