#!/usr/bin/env python3
"""Export the backend OpenAPI schema to the frontend workspace."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "openapi.json"
FRONTEND_GENERATED_DIR = PROJECT_ROOT / "frontend" / "src" / "api" / "generated"


def _normalize_generated_typescript(root: Path) -> int:
    """Normalize generated TypeScript files to keep diffs and checks stable."""

    if not root.exists():
        return 0

    changed_count = 0
    for path in root.rglob("*.ts"):
        original = path.read_text(encoding="utf-8")
        has_final_newline = original.endswith(("\n", "\r"))
        cleaned = "\n".join(line.rstrip(" \t") for line in original.splitlines())
        if has_final_newline:
            cleaned += "\n"
        if cleaned == original:
            continue
        path.write_text(cleaned, encoding="utf-8", newline="\n")
        changed_count += 1
    return changed_count


def export_openapi_schema(app: object) -> bool:
    """Export the OpenAPI schema from an imported FastAPI app."""

    try:
        schema = app.openapi()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )
        print(f"openapi.json exported to {OUTPUT_PATH}")

        frontend_dir = PROJECT_ROOT / "frontend"
        if FRONTEND_GENERATED_DIR.exists():
            shutil.rmtree(FRONTEND_GENERATED_DIR)
            print(f"Removed stale generated client: {FRONTEND_GENERATED_DIR}")
        print("Running `npx orval` to sync frontend client...")
        subprocess.run("npx orval", shell=True, cwd=str(frontend_dir), check=True)
        changed_count = _normalize_generated_typescript(FRONTEND_GENERATED_DIR)
        if changed_count:
            print(f"Normalized generated TypeScript whitespace: {changed_count} files")
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
