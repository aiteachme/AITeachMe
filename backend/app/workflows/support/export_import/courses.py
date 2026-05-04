"""Remote demo-course catalog helpers."""

from __future__ import annotations

import hashlib
import posixpath
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import httpx
import structlog

from app.schemas.export_import import CoursePackageItem
from app.shared.infra.exceptions import (
    DemoCourseCatalogUnavailableError,
    DemoCoursePackageNotFoundError,
    ImportPackageTooLargeError,
)
from app.shared.infra.runtime import get_runtime_data_dir
from app.workflows.support.export_import.limits import (
    MAX_IMPORT_PACKAGE_BYTES,
    MAX_IMPORT_PACKAGE_SIZE_MB,
)

logger = structlog.get_logger()

_DEFAULT_TIMEOUT_S = 15.0
_PACKAGE_PROBE_TIMEOUT_S = 4.0
_PACKAGE_PROBE_MAX_WORKERS = 6
_CATALOG_CACHE_TTL_S = 60.0
_DEMO_COURSES_BASE_URL = "https://raw.githubusercontent.com/aiteachme/assets/main/demo-courses/"
_DEMO_COURSES_INDEX_PATH = "catalog/v1/index.json"
_REMOTE_DESCRIPTOR_CACHE: tuple[float, str, list["_RemoteCourseDescriptor"]] | None = None


@dataclass(frozen=True)
class _RemoteCourseDescriptor:
    identifier: str
    course_name: str
    package_url: str
    package_filename: str
    file_size_bytes: int = 0
    sha256: str | None = None
    exported_at: datetime | None = None
    stats: dict[str, int] | None = None

    def to_item(self) -> CoursePackageItem:
        return CoursePackageItem(
            filename=self.identifier,
            course_name=self.course_name,
            file_size_bytes=self.file_size_bytes,
            exported_at=self.exported_at,
            stats=dict(self.stats or {}),
        )


def list_available_courses() -> list[CoursePackageItem]:
    """List remote demo courses declared in the public assets catalog."""

    try:
        return [item.to_item() for item in _load_remote_course_descriptors()]
    except DemoCourseCatalogUnavailableError as exc:
        logger.warning(
            "demo_course_catalog_unavailable",
            catalog_url=get_demo_courses_index_url(),
            error=str(exc),
        )
        return []


def download_course_package(identifier: str) -> tuple[Path, str]:
    """Download one remote `.atmx` package into a temporary local file."""

    descriptor = get_remote_course_descriptor(identifier)
    if descriptor.file_size_bytes > MAX_IMPORT_PACKAGE_BYTES:
        raise ImportPackageTooLargeError(MAX_IMPORT_PACKAGE_SIZE_MB)

    suffix = Path(descriptor.package_filename or "").suffix or ".atmx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)

    cached_path = _get_valid_cached_package_path(descriptor)
    if cached_path is not None:
        shutil.copyfile(cached_path, tmp_path)
        logger.info(
            "demo_course_package_cache_hit",
            identifier=descriptor.identifier,
            package_filename=descriptor.package_filename,
        )
        return tmp_path, descriptor.package_filename

    try:
        timeout = _get_demo_courses_timeout_s()
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", _with_cache_buster(descriptor.package_url)) as response:
                _raise_for_http_status(
                    response,
                    action=f"下载课程包 `{descriptor.identifier}`",
                )
                _validate_remote_content_length(response)
                hasher = hashlib.sha256() if descriptor.sha256 else None
                bytes_written = 0
                with tmp_path.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        if chunk:
                            bytes_written += len(chunk)
                            if bytes_written > MAX_IMPORT_PACKAGE_BYTES:
                                raise ImportPackageTooLargeError(MAX_IMPORT_PACKAGE_SIZE_MB)
                            if hasher is not None:
                                hasher.update(chunk)
                            fh.write(chunk)
                if hasher is not None and hasher.hexdigest().lower() != descriptor.sha256:
                    raise DemoCourseCatalogUnavailableError(reason="课程包校验失败。")
        _store_cached_package(descriptor, tmp_path)
        return tmp_path, descriptor.package_filename
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def get_remote_course_descriptor(identifier: str) -> _RemoteCourseDescriptor:
    """Resolve one demo course descriptor by its stable identifier."""

    normalized = str(identifier or "").strip()
    if not normalized:
        raise DemoCoursePackageNotFoundError(identifier)

    for descriptor in _load_remote_course_descriptors(probe_packages=False):
        if normalized in {descriptor.identifier, descriptor.package_filename}:
            return descriptor
    raise DemoCoursePackageNotFoundError(normalized)


def get_demo_courses_base_url() -> str:
    """Return the fixed public demo-course root in the project assets repo."""

    return _DEMO_COURSES_BASE_URL


def get_demo_courses_index_url() -> str:
    """Return the fixed remote `index.json` URL for demo courses."""

    return urljoin(get_demo_courses_base_url(), _DEMO_COURSES_INDEX_PATH)


def _get_demo_courses_timeout_s() -> float:
    return _DEFAULT_TIMEOUT_S


def _load_remote_course_descriptors(*, probe_packages: bool = True) -> list[_RemoteCourseDescriptor]:
    catalog_url = get_demo_courses_index_url()
    descriptors = _load_catalog_descriptors(catalog_url)
    if not probe_packages:
        return descriptors
    return _filter_available_remote_course_descriptors(descriptors)


def _load_catalog_descriptors(catalog_url: str) -> list[_RemoteCourseDescriptor]:
    global _REMOTE_DESCRIPTOR_CACHE

    now = time.monotonic()
    if (
        _REMOTE_DESCRIPTOR_CACHE is not None
        and _REMOTE_DESCRIPTOR_CACHE[1] == catalog_url
        and now - _REMOTE_DESCRIPTOR_CACHE[0] <= _CATALOG_CACHE_TTL_S
    ):
        return list(_REMOTE_DESCRIPTOR_CACHE[2])

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

    _REMOTE_DESCRIPTOR_CACHE = (now, catalog_url, descriptors)
    return list(descriptors)


def _demo_course_package_cache_dir() -> Path:
    cache_dir = get_runtime_data_dir() / "cache" / "demo-courses"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_key_for_descriptor(descriptor: _RemoteCourseDescriptor) -> str | None:
    if not descriptor.sha256:
        return None
    digest = descriptor.sha256.lower()
    suffix = Path(descriptor.package_filename or "").suffix or ".atmx"
    return f"{digest}{suffix}"


def _get_valid_cached_package_path(descriptor: _RemoteCourseDescriptor) -> Path | None:
    cache_key = _cache_key_for_descriptor(descriptor)
    if not cache_key:
        return None
    cache_path = _demo_course_package_cache_dir() / cache_key
    if not cache_path.is_file():
        return None
    if descriptor.file_size_bytes > 0 and cache_path.stat().st_size != descriptor.file_size_bytes:
        cache_path.unlink(missing_ok=True)
        return None
    if descriptor.sha256 and _sha256_file(cache_path) != descriptor.sha256.lower():
        cache_path.unlink(missing_ok=True)
        return None
    return cache_path


def _store_cached_package(descriptor: _RemoteCourseDescriptor, package_path: Path) -> None:
    cache_key = _cache_key_for_descriptor(descriptor)
    if not cache_key:
        return
    cache_path = _demo_course_package_cache_dir() / cache_key
    try:
        shutil.copyfile(package_path, cache_path)
    except Exception as exc:  # pragma: no cover - cache best effort
        logger.warning(
            "demo_course_package_cache_store_failed",
            identifier=descriptor.identifier,
            error=str(exc),
        )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            if chunk:
                hasher.update(chunk)
    return hasher.hexdigest()


def _filter_available_remote_course_descriptors(
    descriptors: list[_RemoteCourseDescriptor],
) -> list[_RemoteCourseDescriptor]:
    if not descriptors:
        return []

    max_workers = min(_PACKAGE_PROBE_MAX_WORKERS, len(descriptors))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        availability = list(
            executor.map(
                lambda descriptor: _remote_package_exists(descriptor.package_url),
                descriptors,
            )
        )

    available_descriptors: list[_RemoteCourseDescriptor] = []
    for descriptor, available in zip(descriptors, availability):
        if available:
            available_descriptors.append(descriptor)
            continue
        logger.warning(
            "demo_course_catalog_item_skipped",
            identifier=descriptor.identifier,
            reason="package_url_unavailable",
            package_url=descriptor.package_url,
        )
    return available_descriptors


def _fetch_remote_catalog_payload(catalog_url: str) -> Any:
    timeout = _get_demo_courses_timeout_s()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                _with_cache_buster(catalog_url),
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            _raise_for_http_status(response, action="读取演示课程目录")
            return response.json()
    except DemoCourseCatalogUnavailableError:
        raise
    except Exception as exc:
        raise DemoCourseCatalogUnavailableError(reason=f"无法读取 `{catalog_url}`：{exc}") from exc


def _with_cache_buster(url: str) -> str:
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(("_", str(time.time_ns())))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def _extract_catalog_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("courses", "items", "data", "results"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        if any(key in payload for key in ("course_id", "id", "course_id", "package_url", "download_url")):
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
    course_name = _first_non_empty_str(
        item.get("course_name"),
        item.get("name"),
        item.get("title"),
        item.get("course_name"),
    )
    if not package_ref or not course_name:
        logger.warning(
            "demo_course_catalog_item_skipped",
            index=index,
            reason="missing_course_name_or_package_url",
        )
        return None

    try:
        package_url = _resolve_remote_url(
            package_ref,
            catalog_url=catalog_url,
            base_url=base_url,
        )
        _ensure_demo_package_url_allowed(package_url, base_url=base_url)
    except ValueError as exc:
        logger.warning(
            "demo_course_catalog_item_skipped",
            index=index,
            reason=str(exc),
        )
        return None

    package_filename = _first_non_empty_str(
        item.get("package_filename"),
        item.get("download_name"),
        item.get("filename"),
    ) or _guess_filename_from_url(package_url, fallback=f"course_{index}.atmx")

    identifier = _first_non_empty_str(
        item.get("course_id"),
        item.get("id"),
        item.get("course_id"),
        item.get("filename"),
    ) or Path(package_filename).stem or f"course_{index}"

    return _RemoteCourseDescriptor(
        identifier=identifier,
        course_name=course_name,
        package_url=package_url,
        package_filename=package_filename,
        file_size_bytes=_coerce_int(
            item.get("file_size_bytes"),
            item.get("package_size_bytes"),
            item.get("size_bytes"),
            item.get("size"),
        ),
        sha256=_coerce_sha256(
            item.get("sha256"),
            item.get("package_sha256"),
            item.get("checksum_sha256"),
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


def _ensure_demo_package_url_allowed(url: str, *, base_url: str | None) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("package_url must be an absolute http(s) URL")

    if not base_url:
        return

    base = urlparse(base_url.rstrip("/") + "/")
    same_origin = parsed.scheme == base.scheme and parsed.netloc == base.netloc
    base_path = _normalized_url_path(base.path).rstrip("/") + "/"
    package_path = _normalized_url_path(parsed.path)
    under_base_path = package_path.startswith(base_path)
    if not same_origin or not under_base_path:
        raise ValueError("package_url is outside the configured demo-course base")


def _normalized_url_path(path: str) -> str:
    normalized = posixpath.normpath(unquote(path or "/"))
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


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


def _coerce_sha256(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip().lower()
        if len(text) == 64 and all(char in "0123456789abcdef" for char in text):
            return text
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


def _validate_remote_content_length(response: httpx.Response) -> None:
    raw = response.headers.get("content-length")
    if raw is None:
        return
    try:
        content_length = int(raw)
    except (TypeError, ValueError):
        return
    if content_length > MAX_IMPORT_PACKAGE_BYTES:
        raise ImportPackageTooLargeError(MAX_IMPORT_PACKAGE_SIZE_MB)


def _remote_package_exists(package_url: str) -> bool:
    timeout = _PACKAGE_PROBE_TIMEOUT_S
    url = _with_cache_buster(package_url)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.head(url)
            if response.status_code < 400:
                return True
            if response.status_code in {404, 410}:
                return False

            with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as fallback:
                if fallback.status_code in {404, 410}:
                    return False
                return fallback.status_code < 400
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "demo_course_package_probe_failed",
            package_url=package_url,
            error=str(exc),
        )
        return False


__all__ = [
    "download_course_package",
    "get_demo_courses_base_url",
    "get_demo_courses_index_url",
    "get_remote_course_descriptor",
    "list_available_courses",
]
