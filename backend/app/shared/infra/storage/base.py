"""ArtifactStore 抽象基类。

定义文件/工件存储的统一接口，本地和云端各自实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


def validate_delete_prefix(prefix: str) -> str:
    """Return a normalized, directory-like prefix safe for bulk deletion."""

    normalized = str(prefix or "").replace("\\", "/").strip()
    if (
        not normalized
        or normalized in {".", "/", "./"}
        or normalized.startswith("/")
        or not normalized.endswith("/")
    ):
        raise ValueError("delete_prefix requires a non-root directory prefix ending with '/'")

    segments = [segment for segment in normalized.split("/") if segment]
    if not segments or any(segment in {".", ".."} for segment in segments):
        raise ValueError(f"unsafe delete_prefix value: {prefix}")
    return normalized


class ArtifactStore(ABC):
    """文件与工件存储的统一抽象。"""

    @abstractmethod
    async def read_bytes(self, storage_key: str) -> bytes:
        """读取文件内容。"""

    @abstractmethod
    async def write_bytes(self, storage_key: str, data: bytes) -> None:
        """写入文件内容。"""

    @abstractmethod
    async def write_file(self, storage_key: str, local_path: Path) -> None:
        """将本地文件上传到存储。"""

    @abstractmethod
    async def delete(self, storage_key: str) -> None:
        """删除单个文件。"""

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        """检查文件是否存在。"""

    @abstractmethod
    async def list_prefix(self, prefix: str) -> list[str]:
        """列出指定前缀下的所有 storage_key。"""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int:
        """删除指定前缀下的所有文件，返回删除数量。"""

    @abstractmethod
    async def materialize_to_temp(self, storage_key: str, temp_dir: Path) -> Path:
        """将文件物化到本地临时目录，返回本地路径。

        本地模式直接返回原始路径（零拷贝）；
        云端模式下载到 temp_dir 后返回临时路径。
        """

    def public_url(self, storage_key: str) -> str | None:
        """返回允许公开分发文件的访问 URL；私有资源必须返回 None。"""

        return None


__all__ = ["ArtifactStore", "validate_delete_prefix"]
