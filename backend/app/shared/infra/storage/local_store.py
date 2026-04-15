"""本地文件系统存储实现。"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.shared.infra.runtime import get_runtime_data_dir
from app.shared.infra.storage.base import ArtifactStore


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class LocalArtifactStore(ArtifactStore):
    """基于本地文件系统的 ArtifactStore 实现。"""

    def __init__(self) -> None:
        self._root = get_runtime_data_dir().resolve()

    def _resolve(self, storage_key: str) -> Path:
        raw = Path(str(storage_key or "")).expanduser()
        path = raw.resolve() if raw.is_absolute() else (self._root / raw).resolve()
        if not _is_relative_to(path, self._root):
            raise ValueError(f"storage_key escapes runtime data dir: {storage_key}")
        return path

    async def read_bytes(self, storage_key: str) -> bytes:
        return self._resolve(storage_key).read_bytes()

    async def write_bytes(self, storage_key: str, data: bytes) -> None:
        path = self._resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def write_file(self, storage_key: str, local_path: Path) -> None:
        target = self._resolve(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(local_path), str(target))

    async def delete(self, storage_key: str) -> None:
        self._resolve(storage_key).unlink(missing_ok=True)

    async def exists(self, storage_key: str) -> bool:
        return self._resolve(storage_key).exists()

    async def list_prefix(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []
        root = self._root
        return [
            p.relative_to(root).as_posix()
            for p in sorted(base.rglob("*"))
            if p.is_file()
        ]

    async def delete_prefix(self, prefix: str) -> int:
        base = self._resolve(prefix)
        if not base.exists():
            return 0
        files = [p for p in base.rglob("*") if p.is_file()]
        count = len(files)
        shutil.rmtree(str(base), ignore_errors=True)
        return count

    async def materialize_to_temp(self, storage_key: str, temp_dir: Path) -> Path:
        # 本地模式：直接返回原始路径，零拷贝
        return self._resolve(storage_key)
