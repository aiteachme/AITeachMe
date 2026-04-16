from __future__ import annotations

from pathlib import Path

from app.shared.infra.runtime import get_backend_root, get_runtime_data_dir, get_sqlite_db_path


def test_local_runtime_data_dir_is_backend_root_data() -> None:
    backend_root = Path(__file__).resolve().parents[1]

    assert get_backend_root() == backend_root
    assert get_runtime_data_dir() == backend_root / "data"
    assert get_sqlite_db_path() == backend_root / "data" / "aiteachme.db"
