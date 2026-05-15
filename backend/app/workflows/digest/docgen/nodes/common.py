"""DocGen 节点公共辅助函数。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from app.workflows.digest.common.pedagogy import resolve_effective_chapter_title
from app.workflows.digest.common.contracts import (
    DigestChapterContract,
    DigestConfirmedPlanContract,
    parse_digest_confirmed_plan_contract,
    resolve_digest_retrieval_profile,
)
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import LoggedWorkflowEvent


async def publish_docgen_progress(
    context: WorkflowContext,
    *,
    state: dict[str, Any],
    stage: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """发布轻量的 DocGen 进度事件，供后续实时状态或 WebSocket 复用。"""

    await context.event_bus.publish(
        LoggedWorkflowEvent(
            course_id=state["course_id"],
            workflow_name=context.workflow_name,
            payload={
                "kind": "docgen_progress",
                "stage": stage,
                **(payload or {}),
            },
        )
    )


def normalize_chapter_assignments(
    chapters: list[dict[str, Any]],
    *,
    default_source_file_ids: list[str],
) -> list[dict[str, Any]]:
    return [
        DigestChapterContract.model_validate(chapter).to_assignment(
            default_source_file_ids=default_source_file_ids
        )
        for chapter in chapters
    ]


def normalize_confirmed_plan_contract(plan_payload: dict[str, Any]) -> DigestConfirmedPlanContract:
    return parse_digest_confirmed_plan_contract(plan_payload)


def get_effective_chapter_title(chapter: dict[str, Any], *, fallback_index: int | None = None) -> str:
    return resolve_effective_chapter_title(chapter, chapter_index=fallback_index)


def resolve_docgen_dependency(name: str, default: Any, *, owner_module: str | None = None) -> Any:
    """Resolve debug or test overrides from the owning module instead of graph globals."""

    module_name = owner_module or "app.workflows.digest.docgen.graph"
    try:
        module = import_module(module_name)
    except Exception:
        return default
    return getattr(module, name, default)


def resolve_docgen_retrieval_profile(
    digest_mode: str | None,
    *,
    user_prompt: str | None = None,
    course_name: str | None = None,
) -> str:
    return resolve_digest_retrieval_profile(
        digest_mode,
        user_prompt=user_prompt,
        course_name=course_name,
    )


def serialize_section(section: Any) -> dict[str, Any]:
    if hasattr(section, "model_dump"):
        return section.model_dump(mode="json")
    return dict(section)


def ensure_chapter_heading(title: str, markdown: str) -> str:
    cleaned = (markdown or "").strip()
    if not cleaned.startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}".strip()
    return cleaned + "\n"


def extract_markdown_preview_headings(markdown: str, *, limit: int = 4) -> list[str]:
    secondary: list[str] = []
    primary: list[str] = []
    seen: set[str] = set()

    for raw_line in str(markdown or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if title and title not in seen:
                secondary.append(title)
                seen.add(title)
        elif stripped.startswith("# "):
            title = stripped[2:].strip()
            if title and title not in seen:
                primary.append(title)
                seen.add(title)

    ordered = secondary or primary
    return ordered[: max(1, int(limit))]


__all__ = [
    "ensure_chapter_heading",
    "extract_markdown_preview_headings",
    "get_effective_chapter_title",
    "normalize_chapter_assignments",
    "normalize_confirmed_plan_contract",
    "publish_docgen_progress",
    "resolve_docgen_dependency",
    "resolve_docgen_retrieval_profile",
    "serialize_section",
]
