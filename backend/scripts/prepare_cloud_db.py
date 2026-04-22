"""Prepare Render/PostgreSQL runtime database objects after Alembic migration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.database import prepare_postgres_runtime_schema  # noqa: E402
from app.shared.infra.runtime import is_cloud_mode  # noqa: E402

def main(argv: list[str] | None = None) -> int:
    del argv
    if not is_cloud_mode():
        print("prepare_cloud_db requires APP_MODE=cloud.", file=sys.stderr)
        return 2

    try:
        prepare_postgres_runtime_schema()
    except Exception as exc:  # noqa: BLE001
        print(f"cloud database preparation failed: {exc}", file=sys.stderr)
        return 1

    print("cloud database prepared")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_MODE", "cloud")
    raise SystemExit(main())
