"""Start the cloud app after ensuring the current database is ready.

Render free instances do not support a separate pre-deploy command, so this
script can be used as the service start command. From the repo root with a
native runtime:

    cd backend && python scripts/start_cloud_app.py --host 0.0.0.0 --port $PORT

Inside the Docker image:

    python scripts/start_cloud_app.py --host 0.0.0.0 --port $PORT

When APP_MODE=cloud, it bootstraps the database first, then launches uvicorn.
Without APP_MODE=cloud it only launches uvicorn in the resolved local mode.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.runtime import is_cloud_mode  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap cloud DB if needed, then start uvicorn.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default="9020")
    parser.add_argument("--reset-db", action="store_true")
    return parser


def _run_bootstrap(*, reset_db: bool) -> None:
    command = [sys.executable, str(BACKEND_ROOT / "scripts" / "bootstrap_cloud_db.py")]
    if reset_db:
        command.append("--reset-db")
    subprocess.run(command, cwd=BACKEND_ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if is_cloud_mode():
        try:
            _run_bootstrap(
                reset_db=bool(args.reset_db),
            )
        except subprocess.CalledProcessError as exc:
            print(
                "cloud database bootstrap command failed; app startup aborted "
                f"(exit={exc.returncode})",
                file=sys.stderr,
            )
            return exc.returncode or 1

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
