#!/usr/bin/env python3
"""Check Android-declared API endpoints against the committed OpenAPI schema."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

FRONTEND_OPENAPI_PATH = PROJECT_ROOT / "frontend" / "openapi.json"
ANDROID_API_PATH = (
    PROJECT_ROOT
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "aiteachme"
    / "android"
    / "core"
    / "network"
    / "AiTeachMeApi.kt"
)
ANDROID_ENDPOINTS_PATH = (
    PROJECT_ROOT
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "aiteachme"
    / "android"
    / "core"
    / "network"
    / "generated"
    / "BackendApiEndpoint.kt"
)

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

RETROFIT_ENDPOINT_RE = re.compile(r"@(GET|POST|PUT|PATCH|DELETE)\(\"([^\"]+)\"\)")
BACKEND_ENDPOINT_RE = re.compile(
    r"method\s*=\s*BackendHttpMethod\.([A-Z]+),\s*"
    r"path\s*=\s*\"([^\"]+)\"",
    re.DOTALL,
)


def _normalize_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def _load_openapi_operations() -> set[tuple[str, str]]:
    schema = json.loads(FRONTEND_OPENAPI_PATH.read_text(encoding="utf-8"))
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("frontend/openapi.json does not contain a paths object")

    operations: set[tuple[str, str]] = set()
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method in methods:
            method_upper = str(method).upper()
            if method_upper in HTTP_METHODS:
                operations.add((method_upper, _normalize_path(str(path))))
    return operations


def _extract_retrofit_operations() -> set[tuple[str, str]]:
    source = ANDROID_API_PATH.read_text(encoding="utf-8")
    return {
        (match.group(1), _normalize_path(match.group(2)))
        for match in RETROFIT_ENDPOINT_RE.finditer(source)
    }


def _extract_inventory_operations() -> set[tuple[str, str]]:
    source = ANDROID_ENDPOINTS_PATH.read_text(encoding="utf-8")
    return {
        (match.group(1), _normalize_path(match.group(2)))
        for match in BACKEND_ENDPOINT_RE.finditer(source)
    }


def _format_operation(operation: tuple[str, str]) -> str:
    method, path = operation
    return f"{method} {path}"


def _report_missing(source_name: str, operations: set[tuple[str, str]], openapi_operations: set[tuple[str, str]]) -> bool:
    missing = sorted(operations - openapi_operations)
    if not missing:
        return False

    print(f"{source_name} contains endpoints that are not present in frontend/openapi.json:", file=sys.stderr)
    for operation in missing:
        print(f"  - {_format_operation(operation)}", file=sys.stderr)
    return True


def main() -> int:
    openapi_operations = _load_openapi_operations()
    retrofit_operations = _extract_retrofit_operations()
    inventory_operations = _extract_inventory_operations()

    failed = False
    failed |= _report_missing("AiTeachMeApi.kt", retrofit_operations, openapi_operations)
    failed |= _report_missing("BackendApiEndpoint.kt", inventory_operations, openapi_operations)

    if failed:
        print(
            "\nUpdate Android endpoint declarations to use public OpenAPI routes, "
            "or export the backend OpenAPI schema if the committed schema is stale.",
            file=sys.stderr,
        )
        return 1

    print(
        "Android API contract is in sync with committed OpenAPI "
        f"({len(retrofit_operations)} Retrofit endpoints, {len(inventory_operations)} inventory endpoints checked)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
