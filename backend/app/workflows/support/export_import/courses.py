"""Remote demo-course catalog helpers."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from app.schemas.export_import import CoursePackageItem
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import (
    DemoCourseCatalogNotConfiguredError,
    DemoCourseCatalogUnavailableError,
    DemoCoursePackageNotFoundError,
)
from app.shared.infra.runtime import is_cloud_mode

logger = structlog.get_logger()

_DEFAULT_TIMEOUT_S = 15.0
_DEMO_COURSES_ROOT = "demo-courses/"
_DEMO_COURSES_INDEX_PATH = "catalog/v1/index.json"


@dataclass(frozen=True)
class _RemoteCourseDescriptor:
    identifier: str
    subject_name: str
    package_url: str
    package_filename: str
    file_size_bytes: int = 0
    exported_at: datetime | None = None
    stats: dict[str, int] | None = None

    def to_item(self) -> CoursePackageItem:
        return CoursePackageItem(
            filename=self.identifier,
            subject_name=self.subject_name,
            file_size_bytes=self.file_size_bytes,
            exported_at=self.exported_at,
            stats=dict(self.stats or {}),
        )


def list_available_courses() -> list[CoursePackageItem]:
    """List remote demo courses declared in the configured OSS catalog."""

    if not _demo_courses_enabled():
        return []

    catalog_url = get_demo_courses_index_url()
    if not catalog_url:
        return []
    return [item.to_item() for item in _load_remote_course_descriptors()]


def download_course_package(identifier: str) -> tuple[Path, str]:
    """Download one remote `.atmx` package into a temporary local file."""

    if not _demo_courses_enabled():
        raise DemoCourseCatalogNotConfiguredError()

    descriptor = get_remote_course_descriptor(identifier)
    suffix = Path(descriptor.package_filename or "").suffix or ".atmx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)

    try:
        timeout = _get_demo_courses_timeout_s()
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", descriptor.package_url) as response:
                _raise_for_http_status(
                    response,
                    action=f"下载课程包 `{descriptor.identifier}`",
                )
                with tmp_path.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        if chunk:
                            fh.write(chunk)
        return tmp_path, descriptor.package_filename
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def get_remote_course_descriptor(identifier: str) -> _RemoteCourseDescriptor:
    """Resolve one demo course descriptor by its stable identifier."""

    if not _demo_courses_enabled():
        raise DemoCourseCatalogNotConfiguredError()

    normalized = str(identifier or "").strip()
    if not normalized:
        raise DemoCoursePackageNotFoundError(identifier)

    for descriptor in _load_remote_course_descriptors():
        if normalized in {descriptor.identifier, descriptor.package_filename}:
            return descriptor
    raise DemoCoursePackageNotFoundError(normalized)


def get_demo_courses_base_url() -> str | None:
    """Return the fixed remote demo-course root under the existing public OSS base."""

    value = (get_env("S3_PUBLIC_BASE_URL") or "").strip()
    if not value:
        return None
    return urljoin(value.rstrip("/") + "/", _DEMO_COURSES_ROOT)


def get_demo_courses_index_url() -> str | None:
    """Return the fixed remote `index.json` URL for demo courses."""

    base_url = get_demo_courses_base_url()
    if not base_url:
        return None
    return urljoin(base_url, _DEMO_COURSES_INDEX_PATH)


def _demo_courses_enabled() -> bool:
    return is_cloud_mode()


def _get_demo_courses_timeout_s() -> float:
    return _DEFAULT_TIMEOUT_S


def _load_remote_course_descriptors() -> list[_RemoteCourseDescriptor]:
    catalog_url = get_demo_courses_index_url()
    if not catalog_url:
        raise DemoCourseCatalogNotConfiguredError()

    payload = _fetch_remote_catalog_payload(catalog_url)
    raw_items = _extract_catalog_items(payload)
    base_url = get_demo_courses_base_url()

    descriptors: list[_RemoteCourseDescriptor] = []
    for index, item in enumerate(raw_items, start=1):
        descriptor = _build_remote_course_descriptor(
            item,
            index=index,
            catalog_url=catalog_url,
            base_url=base_url,
        )
        if descriptor is None:
            continue
        descriptors.append(descriptor)
    return descriptors


def _fetch_remote_catalog_payload(catalog_url: str) -> Any:
    timeout = _get_demo_courses_timeout_s()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                catalog_url,
                headers={"Accept": "application/json"},
            )
            _raise_for_http_status(response, action="读取演示课程目录")
            return response.json()
    except DemoCourseCatalogUnavailableError:
        raise
    except Exception as exc:
        raise DemoCourseCatalogUnavailableError(reason=f"无法读取 `{catalog_url}`：{exc}") from exc


def _extract_catalog_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("courses", "items", "data", "results"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        if any(key in payload for key in ("course_id", "id", "slug", "package_url", "download_url")):
            return [payload]

    logger.warning(
        "demo_course_catalog_shape_unrecognized",
        payload_type=type(payload).__name__,
    )
    return []


def _build_remote_course_descriptor(
    item: dict[str, Any],
    *,
    index: int,
    catalog_url: str,
    base_url: str | None,
) -> _RemoteCourseDescriptor | None:
    package_ref = _first_non_empty_str(
        item.get("package_url"),
        item.get("download_url"),
        item.get("package"),
        item.get("url"),
        item.get("path"),
    )
    subject_name = _first_non_empty_str(
        item.get("subject_name"),
        item.get("name"),
        item.get("title"),
        item.get("course_name"),
    )
    if not package_ref or not subject_name:
        logger.warning(
            "demo_course_catalog_item_skipped",
            index=index,
            reason="missing_subject_name_or_package_url",
        )
        return None

    package_url = _resolve_remote_url(
        package_ref,
        catalog_url=catalog_url,
        base_url=base_url,
    )
    package_filename = _first_non_empty_str(
        item.get("package_filename"),
        item.get("download_name"),
        item.get("filename"),
    ) or _guess_filename_from_url(package_url, fallback=f"course_{index}.atmx")

    identifier = _first_non_empty_str(
        item.get("course_id"),
        item.get("id"),
        item.get("slug"),
        item.get("filename"),
    ) or Path(package_filename).stem or f"course_{index}"

    return _RemoteCourseDescriptor(
        identifier=identifier,
        subject_name=subject_name,
        package_url=package_url,
        package_filename=package_filename,
        file_size_bytes=_coerce_int(
            item.get("file_size_bytes"),
            item.get("package_size_bytes"),
            item.get("size_bytes"),
            item.get("size"),
        ),
        exported_at=_coerce_datetime(
            item.get("exported_at"),
            item.get("updated_at"),
            item.get("published_at"),
        ),
        stats=_coerce_stats(item.get("stats") or item.get("counts") or {}),
    )


def _resolve_remote_url(
    value: str,
    *,
    catalog_url: str,
    base_url: str | None,
) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    if raw.startswith(("http://", "https://")):
        return raw
    if base_url:
        return urljoin(base_url, raw.lstrip("/"))
    return urljoin(catalog_url, raw)


def _guess_filename_from_url(url: str, *, fallback: str) -> str:
    name = Path(urlparse(url).path).name
    return name or fallback


def _coerce_int(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _coerce_datetime(*values: Any) -> datetime | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, datetime):
            return value
        raw = str(value).strip()
        if not raw:
            continue
        normalized = raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            continue
    return None


def _coerce_stats(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, int] = {}
    for key, item in value.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            normalized[name] = max(0, int(item))
        except (TypeError, ValueError):
            continue
    return normalized


def _first_non_empty_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _raise_for_http_status(response: httpx.Response, *, action: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DemoCourseCatalogUnavailableError(
            reason=f"{action}失败（HTTP {exc.response.status_code}）。"
        ) from exc


__all__ = [
    "download_course_package",
    "get_demo_courses_base_url",
    "get_demo_courses_index_url",
    "get_remote_course_descriptor",
    "list_available_courses",
]
