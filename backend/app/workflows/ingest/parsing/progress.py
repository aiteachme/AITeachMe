"""Persisted progress reporting for file parsing."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeAlias

import structlog

from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.shared.infra.database import managed_session


ParseProgressCallback: TypeAlias = Callable[[Mapping[str, Any]], None]
logger = structlog.get_logger(__name__)


_STAGE_DEFAULTS: dict[str, tuple[int, str]] = {
    "waiting": (2, "等待解析"),
    "classifying": (4, "识别文件类型"),
    "preparing": (6, "准备解析"),
    "uploading": (8, "上传解析服务"),
    "queued": (10, "等待云端解析"),
    "parsing": (10, "解析正文"),
    "downloading": (92, "下载解析结果"),
    "processing_result": (97, "整理正文与图片"),
    "completed": (100, "解析完成"),
    "failed": (100, "解析失败"),
}


def build_parse_progress_payload(
    *,
    stage: str,
    percent: int | None = None,
    detail: str | None = None,
    provider: str | None = None,
    current_pages: int | None = None,
    total_pages: int | None = None,
) -> dict[str, object]:
    normalized_stage = str(stage or "waiting").strip() or "waiting"
    default_percent, default_detail = _STAGE_DEFAULTS.get(normalized_stage, (2, "处理中"))
    normalized_total = max(int(total_pages or 0), 0) or None
    normalized_current = max(int(current_pages or 0), 0) if current_pages is not None else None
    if normalized_total is not None and normalized_current is not None:
        normalized_current = min(normalized_current, normalized_total)
    normalized_percent = max(0, min(100, int(default_percent if percent is None else percent)))
    return {
        "stage": normalized_stage,
        "percent": normalized_percent,
        "detail": str(detail or default_detail).strip() or default_detail,
        "provider": str(provider or "").strip() or None,
        "current_pages": normalized_current,
        "total_pages": normalized_total,
    }


def serialize_parse_progress(**kwargs: object) -> str:
    return json.dumps(build_parse_progress_payload(**kwargs), ensure_ascii=False)


def notify_parse_progress(
    callback: ParseProgressCallback | None,
    **payload: object,
) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:
        # Progress reporting must never turn a successful provider parse into a failure.
        return


def persist_parse_progress(
    *,
    user_id: str,
    file_id: str,
    stage: str,
    percent: int | None = None,
    detail: str | None = None,
    provider: str | None = None,
    current_pages: int | None = None,
    total_pages: int | None = None,
) -> None:
    payload_json = serialize_parse_progress(
        stage=stage,
        percent=percent,
        detail=detail,
        provider=provider,
        current_pages=current_pages,
        total_pages=total_pages,
    )
    with managed_session() as session:
        raw_file = get_raw_file_by_id(session, file_id)
        if raw_file is None or raw_file.user_id != user_id:
            return
        update_raw_file(session, raw_file, parse_progress_json=payload_json)


class ParseProgressTracker:
    """Aggregate provider callbacks and throttle progress database writes."""

    def __init__(self, *, user_id: str, file_id: str, min_write_interval_s: float = 1.5) -> None:
        self._user_id = user_id
        self._file_id = file_id
        self._min_write_interval_s = max(float(min_write_interval_s), 0.0)
        self._lock = threading.Lock()
        self._chunk_pages: dict[str, int] = {}
        self._parallel_total_pages: int | None = None
        self._last_write_at = 0.0
        self._last_signature: tuple[object, ...] | None = None
        self._pending_payload: dict[str, object] | None = None
        self._highest_percent = 0

    def report(self, event: Mapping[str, Any], *, force: bool = False) -> None:
        with self._lock:
            payload = self._normalize_event(event)
            signature = (
                payload["stage"],
                payload["percent"],
                payload["current_pages"],
                payload["total_pages"],
                payload["provider"],
            )
            now = time.monotonic()
            self._pending_payload = payload
            if signature == self._last_signature:
                return
            if not force and self._last_write_at and now - self._last_write_at < self._min_write_interval_s:
                return
            self._write(payload)
            self._last_signature = signature
            self._last_write_at = now
            self._pending_payload = None

    def stage(
        self,
        stage: str,
        *,
        percent: int | None = None,
        detail: str | None = None,
        provider: str | None = None,
        force: bool = True,
    ) -> None:
        self.report(
            {
                "stage": stage,
                "percent": percent,
                "detail": detail,
                "provider": provider,
            },
            force=force,
        )

    def flush(self) -> None:
        with self._lock:
            if self._pending_payload is None:
                return
            payload = self._pending_payload
            self._write(payload)
            self._last_signature = (
                payload["stage"],
                payload["percent"],
                payload["current_pages"],
                payload["total_pages"],
                payload["provider"],
            )
            self._last_write_at = time.monotonic()
            self._pending_payload = None

    def _normalize_event(self, event: Mapping[str, Any]) -> dict[str, object]:
        stage = str(event.get("stage") or "parsing")
        current_pages = _optional_int(event.get("current_pages"))
        total_pages = _optional_int(event.get("total_pages"))
        chunk_id = str(event.get("chunk_id") or "").strip()
        overall_total = _optional_int(event.get("overall_total_pages"))
        if overall_total is not None and overall_total > 0:
            self._parallel_total_pages = max(self._parallel_total_pages or 0, overall_total)
        if chunk_id:
            previous_chunk_pages = self._chunk_pages.setdefault(chunk_id, 0)
            if current_pages is not None:
                self._chunk_pages[chunk_id] = max(previous_chunk_pages, current_pages, 0)

        # Once chunk progress starts, never expose a provider's per-chunk denominator.
        # Some polling responses omit the current page count while retaining e.g. total=10.
        if self._chunk_pages and stage == "parsing":
            current_pages = sum(self._chunk_pages.values())
            total_pages = self._parallel_total_pages or total_pages

        percent = _optional_int(event.get("percent"))
        if stage == "parsing" and current_pages is not None and total_pages:
            page_ratio = max(0.0, min(1.0, current_pages / total_pages))
            percent = round(10 + page_ratio * 80)

        payload = build_parse_progress_payload(
            stage=stage,
            percent=percent,
            detail=str(event.get("detail") or "") or None,
            provider=str(event.get("provider") or "") or None,
            current_pages=current_pages,
            total_pages=total_pages,
        )
        payload["percent"] = max(int(payload["percent"]), self._highest_percent)
        return payload

    def _write(self, payload: Mapping[str, object]) -> None:
        self._highest_percent = max(self._highest_percent, int(payload["percent"]))
        try:
            persist_parse_progress(
                user_id=self._user_id,
                file_id=self._file_id,
                stage=str(payload["stage"]),
                percent=int(payload["percent"]),
                detail=str(payload["detail"]),
                provider=str(payload.get("provider") or "") or None,
                current_pages=_optional_int(payload.get("current_pages")),
                total_pages=_optional_int(payload.get("total_pages")),
            )
        except Exception as exc:
            logger.warning(
                "parse_progress_persist_failed",
                file_id=self._file_id,
                stage=str(payload["stage"]),
                error=str(exc),
            )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ParseProgressCallback",
    "ParseProgressTracker",
    "build_parse_progress_payload",
    "notify_parse_progress",
    "persist_parse_progress",
    "serialize_parse_progress",
]
