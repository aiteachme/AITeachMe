"""Filesystem helpers shared by file and knowledge services."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def get_data_dir() -> Path:
    return Path(get_settings().data_dir)


def build_subject_dir(subject: str) -> Path:
    return get_data_dir() / subject


def build_raw_dir(subject: str) -> Path:
    return build_subject_dir(subject) / "raw"


def build_markdown_dir(subject: str) -> Path:
    return build_subject_dir(subject) / "markdown"


def build_assets_dir(subject: str) -> Path:
    return build_subject_dir(subject) / "assets"


def build_temp_dir(subject: str) -> Path:
    return build_subject_dir(subject) / "temp"


def build_raw_file_path(subject: str, record_id: int, extension: str) -> Path:
    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return build_raw_dir(subject) / f"{record_id}{normalized_extension}"


def build_markdown_path(subject: str, raw_file_id: int) -> Path:
    return build_markdown_dir(subject) / f"{raw_file_id}.md"


def build_asset_dir(subject: str, raw_file_id: int) -> Path:
    return build_assets_dir(subject) / str(raw_file_id)


def ensure_parent_dirs(*paths: Path) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
