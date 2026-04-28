#!/usr/bin/env python3
"""Check that the committed frontend OpenAPI schema matches the backend app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_OPENAPI_PATH = PROJECT_ROOT / "frontend" / "openapi.json"


def _load_backend_schema() -> dict[str, object]:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.main import app

    return app.openapi()


def _load_frontend_schema() -> dict[str, object]:
    return json.loads(FRONTEND_OPENAPI_PATH.read_text(encoding="utf-8"))


def _path_keys(schema: dict[str, object]) -> set[str]:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return set()
    return {str(path) for path in paths}


def _canonical_schema(schema: dict[str, object]) -> str:
    return json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    backend_schema = _load_backend_schema()
    frontend_schema = _load_frontend_schema()

    if _canonical_schema(backend_schema) == _canonical_schema(frontend_schema):
        print("OpenAPI schema is in sync.")
        return 0

    backend_paths = _path_keys(backend_schema)
    frontend_paths = _path_keys(frontend_schema)
    backend_only = sorted(backend_paths - frontend_paths)
    frontend_only = sorted(frontend_paths - backend_paths)

    print("frontend/openapi.json is out of sync with backend OpenAPI.", file=sys.stderr)
    if backend_only:
        print("\nBackend-only paths:", file=sys.stderr)
        for path in backend_only:
            print(f"  + {path}", file=sys.stderr)
    if frontend_only:
        print("\nFrontend-only paths:", file=sys.stderr)
        for path in frontend_only:
            print(f"  - {path}", file=sys.stderr)
    if not backend_only and not frontend_only:
        print("\nPaths match, but operations/components differ.", file=sys.stderr)
    print(
        "\nRun `cd backend && python scripts/export_api_docs.py` to regenerate OpenAPI and Orval clients.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
