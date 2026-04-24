"""Windows desktop entrypoint for the bundled FastAPI backend."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import traceback

_log_stream = None


def configure_desktop_environment() -> None:
    """Set safe local defaults before importing the FastAPI app."""

    os.environ.setdefault("APP_MODE", "local")
    os.environ.setdefault("AUTH_ENABLED", "false")
    os.environ.setdefault(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5180,http://127.0.0.1:5180,null,file://",
    )

    data_dir = os.environ.get("AITEACHME_DATA_DIR")
    if data_dir:
        Path(data_dir).expanduser().mkdir(parents=True, exist_ok=True)


def get_log_file() -> Path:
    configured_log = os.environ.get("AITEACHME_BACKEND_LOG_FILE")
    if configured_log:
        return Path(configured_log).expanduser().resolve()

    data_dir = os.environ.get("AITEACHME_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser().resolve() / "backend.log"

    return Path.cwd() / "backend.log"


def write_startup_error() -> None:
    log_file = get_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("\n=== AiTeachMe backend startup error ===\n")
        handle.write(traceback.format_exc())
        handle.write("\n")


def ensure_standard_streams() -> None:
    global _log_stream

    if sys.stdout is not None and sys.stderr is not None:
        return

    log_file = get_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _log_stream = log_file.open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log_stream
    if sys.stderr is None:
        sys.stderr = _log_stream


def build_uvicorn_log_config() -> dict:
    from uvicorn.config import LOGGING_CONFIG

    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["default"]["use_colors"] = False
    log_config["formatters"]["access"]["use_colors"] = False
    return log_config


def main() -> None:
    configure_desktop_environment()
    ensure_standard_streams()

    port = int(os.environ.get("AITEACHME_BACKEND_PORT", "8010"))
    log_level = os.environ.get("AITEACHME_BACKEND_LOG_LEVEL", "info")

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level=log_level,
        log_config=build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        write_startup_error()
        raise
