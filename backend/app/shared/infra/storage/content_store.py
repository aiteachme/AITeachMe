"""ContentStore — 完整的文件生命周期管理器。

业务代码只依赖 ContentStore，不需要知道当前是 local 还是 cloud。
ContentStore 包装底层 ArtifactStore，提供三大类接口：

1. **Key 构建** — 统一返回 ``str`` key，屏蔽 Path vs storage_key 差异
2. **文本/JSON 便捷操作** — 内部处理编解码、异常吞并、default 返回
3. **工作目录 & 批量上传** — ``work_dir()`` 上下文 + ``upload_dir()``
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, TypeVar

from pydantic import BaseModel

from app.shared.infra.storage.base import ArtifactStore, validate_delete_prefix
from app.shared.infra.storage.subject_scope import (
    SubjectStorageScope,
    UserFileStorageScope,
    build_subject_storage_scope,
    build_user_file_storage_scope,
)

T = TypeVar("T", bound=BaseModel)


class ContentStore:
    """ArtifactStore 的上层业务包装。

    所有业务代码应该通过此类访问存储，而不是直接调用 ArtifactStore 或
    检查 ``is_cloud_mode``。
    """

    def __init__(self, inner: ArtifactStore) -> None:
        self._inner = inner

    @property
    def raw(self) -> ArtifactStore:
        """暴露底层 ArtifactStore（极少数需要直接访问的场景）。"""
        return self._inner

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  1. Key 构建（统一返回 str，屏蔽 Path vs storage_key）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def subject_scope(*, user_id: str, subject_id: str) -> SubjectStorageScope:
        """Return the canonical persisted storage scope for one subject."""

        return build_subject_storage_scope(user_id=user_id, subject_id=subject_id)

    @staticmethod
    def user_file_scope(*, user_id: str) -> UserFileStorageScope:
        """Return the canonical persisted storage scope for one user's file library."""

        return build_user_file_storage_scope(user_id=user_id)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  2. 文本 / JSON 便捷操作
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        """读取文本内容。读失败（文件不存在等）返回 default。"""
        try:
            data = await self._inner.read_bytes(key)
            return data.decode("utf-8")
        except Exception:
            return default

    async def write_text(self, key: str, content: str) -> None:
        """写入文本内容。"""
        await self._inner.write_bytes(key, content.encode("utf-8"))

    async def read_json(self, key: str, model: type[T]) -> T | None:
        """读取并反序列化为 Pydantic 模型。失败返回 None。"""
        text = await self.read_text(key)
        if text is None:
            return None
        try:
            return model.model_validate_json(text)
        except Exception:
            return None

    async def write_json(self, key: str, model: BaseModel) -> None:
        """将 Pydantic 模型序列化写入。"""
        await self.write_text(key, model.model_dump_json(indent=2))

    async def read_json_raw(self, key: str) -> dict | list | None:
        """读取并解析为原始 dict/list。失败返回 None。"""
        import json as _json

        text = await self.read_text(key)
        if text is None:
            return None
        try:
            return _json.loads(text)
        except Exception:
            return None

    async def write_json_raw(self, key: str, obj: dict | list) -> None:
        """将原始 dict/list 序列化写入。"""
        import json as _json

        await self.write_text(key, _json.dumps(obj, ensure_ascii=False, indent=2))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  3. 工作目录 & 批量操作
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @contextmanager
    def work_dir(self, prefix: str = "atm_") -> Generator[Path, None, None]:
        """创建临时工作目录，退出时自动清理。

        local 和 cloud 模式都使用临时目录做中间处理，
        保证统一行为（local 模式下 write_text/write_bytes 会写到
        data_dir 下的正确位置，临时目录只是 parsing 的工作区）。
        """
        tmp = Path(tempfile.mkdtemp(prefix=prefix))
        try:
            yield tmp
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def upload_dir(self, local_dir: Path, key_prefix: str) -> int:
        """将本地目录的所有文件上传到指定 key 前缀下。返回上传文件数。"""
        count = 0
        for file in sorted(local_dir.rglob("*")):
            if file.is_file():
                relative = file.relative_to(local_dir).as_posix()
                key = f"{key_prefix}{relative}" if not key_prefix.endswith("/") \
                    else f"{key_prefix}{relative}"
                await self._inner.write_file(key, file)
                count += 1
        return count

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  代理常用底层方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def read_bytes(self, key: str) -> bytes:
        return await self._inner.read_bytes(key)

    async def write_bytes(self, key: str, data: bytes) -> None:
        await self._inner.write_bytes(key, data)

    async def write_file(self, key: str, local_path: Path) -> None:
        await self._inner.write_file(key, local_path)

    async def exists(self, key: str) -> bool:
        return await self._inner.exists(key)

    async def delete(self, key: str) -> None:
        await self._inner.delete(key)

    async def delete_prefix(self, prefix: str) -> int:
        return await self._inner.delete_prefix(validate_delete_prefix(prefix))

    async def list_prefix(self, prefix: str) -> list[str]:
        return await self._inner.list_prefix(prefix)

    async def materialize(self, key: str, temp_dir: Path) -> Path:
        """将文件物化到本地临时目录。local 模式零拷贝。"""
        return await self._inner.materialize_to_temp(key, temp_dir)

    def public_url(self, key: str) -> str | None:
        return self._inner.public_url(key)
