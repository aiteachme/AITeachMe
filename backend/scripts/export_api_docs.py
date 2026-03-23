#!/usr/bin/env python3
"""Export the backend OpenAPI schema to the frontend workspace."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "openapi.json"


def export_openapi_schema(app: object) -> bool:
    """Export the OpenAPI schema from an imported FastAPI app."""

    try:
        schema = app.openapi()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"openapi.json exported to {OUTPUT_PATH}")

        frontend_dir = PROJECT_ROOT / "frontend"
        print("Running `npx orval` to sync frontend client...")
        subprocess.run("npx orval", shell=True, cwd=str(frontend_dir), check=False)
        return True
    except Exception as exc:
        print(f"Export OpenAPI failed: {exc}")
        return False


def main() -> int:
    """CLI entrypoint."""

    print(f"Output path: {OUTPUT_PATH}")

    try:
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            __import__("python_multipart")
        except ModuleNotFoundError:
            stub = types.ModuleType("python_multipart")
            stub.__version__ = "0.0.13"
            sys.modules["python_multipart"] = stub

        from app.main import app

        return 0 if export_openapi_schema(app) else 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
