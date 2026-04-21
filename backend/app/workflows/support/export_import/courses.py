"""Shared course package catalog helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import structlog

from app.schemas.export_import import CoursePackageItem
from app.utils.path_helpers import build_courses_dir
from app.workflows.support.export_import.exports import (
    SUPPORTED_FORMAT_VERSIONS,
    _ExportManifest,
)

logger = structlog.get_logger()


def list_available_courses() -> list[CoursePackageItem]:
    """Scan the shared course directory and return valid package summaries."""

    courses_dir = get_courses_dir_path()
    items: list[CoursePackageItem] = []
    for path in sorted(courses_dir.glob("*.atmx")):
        if not path.is_file():
            continue
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    continue
                manifest = _ExportManifest.model_validate_json(zf.read("manifest.json"))
            if manifest.format_version not in SUPPORTED_FORMAT_VERSIONS:
                logger.warning(
                    "course_package_scan_skipped_unsupported_version",
                    file=path.name,
                    format_version=manifest.format_version,
                )
                continue
            items.append(
                CoursePackageItem(
                    filename=path.name,
                    subject_name=manifest.subject.name,
                    file_size_bytes=path.stat().st_size,
                    exported_at=manifest.exported_at,
                    stats=manifest.stats.model_dump(),
                )
            )
        except Exception as exc:
            logger.warning("course_package_scan_error", file=path.name, error=str(exc))
    return items


def get_courses_dir_path() -> Path:
    """Return the local shared-course directory under runtime data."""

    courses_dir = build_courses_dir()
    courses_dir.mkdir(parents=True, exist_ok=True)
    return courses_dir


__all__ = ["get_courses_dir_path", "list_available_courses"]
