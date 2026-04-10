"""DocGen 节点公共辅助函数。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from app.teaching.documents import resolve_effective_chapter_title
from app.workflows.digest.shared.contracts import (
    DigestChapterContract,
    DigestConfirmedPlanContract,
    parse_digest_confirmed_plan_contract,
    resolve_digest_course_type,
    resolve_digest_retrieval_profile,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import LoggedWorkflowEvent


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
            subject=state["subject"],
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
    default_source_file_ids: list[int],
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


def resolve_docgen_course_type(digest_mode: str | None) -> str:
    return resolve_digest_course_type(digest_mode)


def resolve_docgen_retrieval_profile(digest_mode: str | None) -> str:
    return resolve_digest_retrieval_profile(digest_mode)


def serialize_section(section: Any) -> dict[str, Any]:
    if hasattr(section, "model_dump"):
        return section.model_dump(mode="json")
    return dict(section)


def ensure_chapter_heading(title: str, markdown: str) -> str:
    cleaned = (markdown or "").strip()
    if not cleaned.startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}".strip()
    return cleaned + "\n"


def build_examine_markdown(question_titles: list[str]) -> str:
    prompts = question_titles or ["整份文档"]
    lines = ["# 练习与自检", "", "## 简答题", ""]
    for index, title in enumerate(prompts, start=1):
        lines.append(f"{index}. 请用自己的话解释《{title}》最重要的知识点，并补一个你能想到的例子。")
    lines.extend(
        [
            "",
            "## 复盘问题",
            "",
            "- 现在哪一章你仍然最不确定？原因是什么？",
            "- 哪个公式、定义或推理步骤最值得你再回头看一遍？",
        ]
    )
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "build_examine_markdown",
    "ensure_chapter_heading",
    "get_effective_chapter_title",
    "normalize_chapter_assignments",
    "normalize_confirmed_plan_contract",
    "publish_docgen_progress",
    "resolve_docgen_dependency",
    "resolve_docgen_course_type",
    "resolve_docgen_retrieval_profile",
    "serialize_section",
]
