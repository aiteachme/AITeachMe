"""Resolve upload smoke-test parameters from upload settings."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


_DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "app/shared/infra/settings/defaults.py"
_DEFAULT_NAME = "DEFAULT_INGEST_MAX_UPLOAD_SIZE_MB"
_LEGACY_PROXY_LIMIT_PROBE_MB = 13


def _read_code_default_upload_limit_mb() -> int:
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


def _read_runtime_upload_limit_mb() -> int:
    from app.shared.infra.settings import get_settings, reset_project_settings_cache

    reset_project_settings_cache()
    value = int(get_settings().ingest.max_upload_size_mb)
    if value < 1:
        raise RuntimeError("settings.ingest.max_upload_size_mb must be a positive integer")
    return value


def _probe_size_mb(upload_limit_mb: int, *, max_probe_mb: int) -> int:
    if max_probe_mb < 1:
        raise RuntimeError("max_probe_mb must be a positive integer")
    if upload_limit_mb > max_probe_mb:
        return max_probe_mb
    return max(1, upload_limit_mb - 1)


def resolve_upload_probe(*, source: str, max_probe_mb: int) -> dict[str, int | str]:
    if source == "runtime":
        upload_limit_mb = _read_runtime_upload_limit_mb()
    elif source == "code-default":
        upload_limit_mb = _read_code_default_upload_limit_mb()
    else:
        raise RuntimeError(f"Unsupported upload probe source: {source}")

    upload_probe_mb = _probe_size_mb(upload_limit_mb, max_probe_mb=max_probe_mb)
    return {
        "upload_limit_mb": upload_limit_mb,
        "upload_probe_bytes": upload_probe_mb * 1024 * 1024,
        "upload_probe_label": f"{upload_probe_mb}MiB",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("code-default", "runtime"),
        default="code-default",
        help="Use code defaults from defaults.py or the effective runtime settings.",
    )
    parser.add_argument(
        "--max-probe-mb",
        type=int,
        default=_LEGACY_PROXY_LIMIT_PROBE_MB,
        help="Upper bound for the smoke-test body size.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    values = resolve_upload_probe(source=args.source, max_probe_mb=args.max_probe_mb)
    upload_limit_mb = values["upload_limit_mb"]
    upload_probe_bytes = values["upload_probe_bytes"]
    upload_probe_label = values["upload_probe_label"]
    print(f"upload_limit_mb={upload_limit_mb}")
    print(f"upload_probe_bytes={upload_probe_bytes}")
    print(f"upload_probe_label={upload_probe_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
