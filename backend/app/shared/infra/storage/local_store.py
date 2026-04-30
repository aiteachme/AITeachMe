"""本地文件系统存储实现。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.shared.infra.runtime import get_runtime_data_dir
from app.shared.infra.storage.base import ArtifactStore, validate_delete_prefix


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _to_os_path(path: Path) -> str:
    """Return a filesystem path that can address long Windows paths."""

    value = str(path if path.is_absolute() else path.resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value.lstrip("\\")
    return "\\\\?\\" + value


def _from_os_path(value: str) -> str:
    if os.name != "nt":
        return value
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value.removeprefix("\\\\?\\UNC\\")
    if value.startswith("\\\\?\\"):
        return value.removeprefix("\\\\?\\")
    return value


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
        with open(_to_os_path(self._resolve(storage_key)), "rb") as file:
            return file.read()

    async def write_bytes(self, storage_key: str, data: bytes) -> None:
        path = self._resolve(storage_key)
        os.makedirs(_to_os_path(path.parent), exist_ok=True)
        with open(_to_os_path(path), "wb") as file:
            file.write(data)

    async def write_file(self, storage_key: str, local_path: Path) -> None:
        target = self._resolve(storage_key)
        os.makedirs(_to_os_path(target.parent), exist_ok=True)
        shutil.copy2(_to_os_path(local_path), _to_os_path(target))

    async def delete(self, storage_key: str) -> None:
        try:
            os.remove(_to_os_path(self._resolve(storage_key)))
        except FileNotFoundError:
            pass

    async def exists(self, storage_key: str) -> bool:
        return os.path.exists(_to_os_path(self._resolve(storage_key)))

    async def list_prefix(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not os.path.exists(_to_os_path(base)):
            return []
        root = self._root
        keys: list[str] = []
        for dirpath, _, filenames in os.walk(_to_os_path(base)):
            for filename in filenames:
                path = Path(_from_os_path(os.path.join(dirpath, filename)))
                keys.append(path.relative_to(root).as_posix())
        return sorted(keys)

    async def delete_prefix(self, prefix: str) -> int:
        base = self._resolve(validate_delete_prefix(prefix))
        base_os_path = _to_os_path(base)
        if not os.path.exists(base_os_path):
            return 0
        count = sum(len(filenames) for _, _, filenames in os.walk(base_os_path))
        shutil.rmtree(base_os_path, ignore_errors=True)
        return count

    async def materialize_to_temp(self, storage_key: str, temp_dir: Path) -> Path:
        # 本地模式：直接返回原始路径，零拷贝
        path = self._resolve(storage_key)
        if os.name == "nt" and len(str(path)) >= 260:
            return Path(_to_os_path(path))
        return path
