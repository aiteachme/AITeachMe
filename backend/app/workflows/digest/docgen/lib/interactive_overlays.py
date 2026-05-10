"""Persist and inject user-created interactive HTML blocks for DocGen docs."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.shared.infra.storage import CourseStorageScope, get_content_store, run_store_sync
from app.workflows.digest.docgen.lib.interactive_html import build_interactive_markdown_link

_OVERLAYS_FILENAME = "interactive_overlays.json"
_OVERLAY_MARKER_PREFIX = "ATM_INTERACTIVE_OVERLAY"
_PLAN_MARKER_PREFIX = "ATM_INTERACTIVE_PLAN"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_PLAN_MARKER_RE = re.compile(rf"^\s*<!--\s*{_PLAN_MARKER_PREFIX}:(?P<plan_id>[^>]+?)\s*-->\s*$")
_SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_LOCK_GUARD = Lock()
_LOCKS: dict[str, asyncio.Lock] = {}


def interactive_overlays_key(course_scope: CourseStorageScope) -> str:
    return course_scope.knowledge_doc_key(_OVERLAYS_FILENAME)


def _get_overlay_lock(key: str) -> asyncio.Lock:
    with _LOCK_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[key] = lock
        return lock


@asynccontextmanager
async def interactive_overlay_reference_guard(
    course_scope: CourseStorageScope,
    *,
    version_no: int,
    client_reference_id: str | None,
) -> AsyncIterator[None]:
    reference_id = str(client_reference_id or "").strip()
    if not reference_id:
        yield
        return

    key = f"{interactive_overlays_key(course_scope)}:reference:{int(version_no or 0)}:{reference_id}"
    lock = _get_overlay_lock(key)
    async with lock:
        yield


def _text_to_id(text: str) -> str:
    slug = _SLUG_RE.sub("-", str(text or "").strip().lower()).strip("-")
    return slug or "section"


def _heading_text(raw: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", raw)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return text.strip()


def _iter_headings(markdown: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    headings: list[dict[str, Any]] = []
    for match in _HEADING_RE.finditer(markdown):
        title = _heading_text(match.group(2))
        base_id = _text_to_id(title)
        count = counts.get(base_id, 0) + 1
        counts[base_id] = count
        heading_id = base_id if count == 1 else f"{base_id}-{count}"
        headings.append(
            {
                "id": heading_id,
                "level": len(match.group(1)),
                "title": title,
                "start": match.start(),
                "end": match.end(),
            }
        )
    return headings


def _normalize_items(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        items = raw.get("items")
    else:
        items = raw
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            normalized.append(dict(item))
    return normalized


def _matches_client_reference(
    item: Mapping[str, Any],
    *,
    version_no: int,
    client_reference_id: str,
) -> bool:
    return (
        int(item.get("version_no") or 0) == int(version_no or 0)
        and str(item.get("client_reference_id") or "").strip() == client_reference_id
    )


async def read_interactive_overlays(course_scope: CourseStorageScope) -> list[dict[str, Any]]:
    raw = await get_content_store().read_json_raw(interactive_overlays_key(course_scope))
    return _normalize_items(raw)


async def find_interactive_overlay_by_client_reference(
    course_scope: CourseStorageScope,
    *,
    version_no: int,
    client_reference_id: str | None,
) -> dict[str, Any] | None:
    reference_id = str(client_reference_id or "").strip()
    if not reference_id:
        return None
    existing = await read_interactive_overlays(course_scope)
    for item in reversed(existing):
        if _matches_client_reference(
            item,
            version_no=version_no,
            client_reference_id=reference_id,
        ):
            return dict(item)
    return None


def load_current_interactive_overlays(
    course_scope: CourseStorageScope,
    *,
    version_no: int,
) -> list[dict[str, Any]]:
    raw = run_store_sync(get_content_store().read_json_raw, interactive_overlays_key(course_scope))
    items = _normalize_items(raw)
    return [item for item in items if int(item.get("version_no") or 0) == int(version_no or 0)]


async def append_interactive_overlay(
    course_scope: CourseStorageScope,
    *,
    overlay: Mapping[str, Any],
) -> list[dict[str, Any]]:
    key = interactive_overlays_key(course_scope)
    lock = _get_overlay_lock(key)
    async with lock:
        existing = await read_interactive_overlays(course_scope)
        reference_id = str(overlay.get("client_reference_id") or "").strip()
        version_no = int(overlay.get("version_no") or 0)
        if reference_id:
            existing = [
                item
                for item in existing
                if not _matches_client_reference(
                    item,
                    version_no=version_no,
                    client_reference_id=reference_id,
                )
            ]
        merged = [*existing, dict(overlay)]
        await get_content_store().write_json_raw(
            key,
            {
                "schema": "docgen_interactive_overlays.v1",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "items": merged,
            },
        )
        return merged


def build_overlay_markdown_block(overlay: Mapping[str, Any]) -> str:
    overlay_id = str(overlay.get("overlay_id") or "").strip()
    title = str(overlay.get("title") or "交互演示").strip()
    preview_url = str(overlay.get("preview_url") or "").strip()
    if not preview_url:
        return ""
    link_block = build_interactive_markdown_link(preview_url=preview_url, link_label=title)
    return f"<!-- {_OVERLAY_MARKER_PREFIX}:{overlay_id} -->\n{link_block}".strip()


def _section_end_for_heading(headings: Sequence[dict[str, Any]], index: int, markdown_len: int) -> int:
    current = headings[index]
    level = int(current["level"])
    for candidate in headings[index + 1 :]:
        if int(candidate["level"]) <= level:
            return int(candidate["start"])
    return markdown_len


def _strip_resolved_plan_blocks(markdown: str, *, overlays: Sequence[Mapping[str, Any]]) -> str:
    resolved_plan_ids = {
        str(item.get("client_reference_id") or "").strip()
        for item in overlays
        if str(item.get("client_reference_id") or "").strip()
    }
    if not resolved_plan_ids:
        return markdown

    lines = markdown.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        marker = _PLAN_MARKER_RE.match(lines[index])
        plan_id = marker.group("plan_id").strip() if marker else ""
        if plan_id and plan_id in resolved_plan_ids:
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines) and "knowledge-docs/interactive-auto" in lines[index]:
                index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept).rstrip() + "\n"


def apply_interactive_overlays_to_markdown(
    markdown: str,
    *,
    overlays: Sequence[Mapping[str, Any]],
) -> str:
    if not markdown.strip() or not overlays:
        return markdown
    markdown = _strip_resolved_plan_blocks(markdown, overlays=overlays)
    headings = _iter_headings(markdown)
    if not headings:
        blocks = [build_overlay_markdown_block(item) for item in overlays]
        blocks = [block for block in blocks if block and block not in markdown]
        return (markdown.rstrip() + "\n\n" + "\n\n".join(blocks)).rstrip() + "\n" if blocks else markdown

    insertions: list[tuple[int, int, str]] = []
    for order, overlay in enumerate(overlays):
        overlay_id = str(overlay.get("overlay_id") or "").strip()
        if overlay_id and f"{_OVERLAY_MARKER_PREFIX}:{overlay_id}" in markdown:
            continue
        block = build_overlay_markdown_block(overlay)
        if not block:
            continue
        anchor_id = str(overlay.get("anchor_id") or "").strip()
        heading_index = next((idx for idx, item in enumerate(headings) if item["id"] == anchor_id), -1)
        insert_at = _section_end_for_heading(headings, heading_index, len(markdown)) if heading_index >= 0 else len(markdown)
        insertions.append((insert_at, order, block))

    if not insertions:
        return markdown

    updated = markdown
    for insert_at, _order, block in sorted(insertions, key=lambda item: (item[0], item[1]), reverse=True):
        prefix = updated[:insert_at].rstrip()
        suffix = updated[insert_at:].lstrip("\n")
        middle = f"\n\n{block}\n\n"
        updated = prefix + middle + suffix
    return updated.rstrip() + "\n"


__all__ = [
    "append_interactive_overlay",
    "apply_interactive_overlays_to_markdown",
    "build_overlay_markdown_block",
    "find_interactive_overlay_by_client_reference",
    "interactive_overlay_reference_guard",
    "interactive_overlays_key",
    "load_current_interactive_overlays",
    "read_interactive_overlays",
]
