"""Start the cloud app after validating and preparing every cloud dependency.

Render free instances do not support a separate pre-deploy command, so this
script can be used as the service start command. From the repo root with a
native runtime:

    cd backend && python scripts/start_cloud_app.py --host 0.0.0.0 --port $PORT

Inside the Docker image:

    python scripts/start_cloud_app.py --host 0.0.0.0 --port $PORT

This is a cloud-only entrypoint. It refuses to start unless the process is
explicitly configured for PostgreSQL, S3 storage, and cloud authentication.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.runtime import collect_cloud_runtime_config_errors  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap cloud DB if needed, then start uvicorn.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default="9020")
    parser.add_argument("--reset-db", action="store_true")
    return parser


def _run_bootstrap(*, reset_db: bool) -> None:
    from scripts import bootstrap_cloud_db

    bootstrap_args: list[str] = []
    if reset_db:
        bootstrap_args.append("--reset-db")
    exit_code = bootstrap_cloud_db.main(bootstrap_args)
    if exit_code:
        raise RuntimeError(f"cloud database bootstrap failed (exit={exit_code})")


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    config_errors = collect_cloud_runtime_config_errors()
    if config_errors:
        print("cloud startup configuration is invalid:", file=sys.stderr)
        for error in config_errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    try:
        _run_bootstrap(
            reset_db=bool(args.reset_db),
        )
    except RuntimeError as exc:
        print(
            f"{exc}; app startup aborted",
            file=sys.stderr,
        )
        return 1

    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        str(args.host),
        "--port",
        str(args.port),
    ]
    os.chdir(BACKEND_ROOT)
    os.execvpe(uvicorn_cmd[0], uvicorn_cmd, os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
