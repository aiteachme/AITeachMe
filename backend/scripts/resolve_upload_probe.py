"""Resolve upload smoke-test parameters from the code-owned upload default."""

from __future__ import annotations

import ast
from pathlib import Path


_DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "app/shared/infra/settings/defaults.py"
_DEFAULT_NAME = "DEFAULT_INGEST_MAX_UPLOAD_SIZE_MB"
_LEGACY_PROXY_LIMIT_PROBE_MB = 13


def _read_default_upload_limit_mb() -> int:
    module = ast.parse(_DEFAULTS_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == _DEFAULT_NAME:
                value = ast.literal_eval(node.value)
                if not isinstance(value, int) or value < 1:
                    raise RuntimeError(f"{_DEFAULT_NAME} must be a positive integer")
                return value
    raise RuntimeError(f"{_DEFAULT_NAME} not found in {_DEFAULTS_PATH}")


def _probe_size_mb(upload_limit_mb: int) -> int:
    if upload_limit_mb > _LEGACY_PROXY_LIMIT_PROBE_MB:
        return _LEGACY_PROXY_LIMIT_PROBE_MB
    return max(1, upload_limit_mb - 1)


def main() -> int:
    upload_limit_mb = _read_default_upload_limit_mb()
    upload_probe_mb = _probe_size_mb(upload_limit_mb)
    print(f"upload_limit_mb={upload_limit_mb}")
    print(f"upload_probe_bytes={upload_probe_mb * 1024 * 1024}")
    print(f"upload_probe_label={upload_probe_mb}MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
