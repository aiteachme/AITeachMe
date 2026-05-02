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
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile
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


def build_examine_markdown(
    question_titles: list[str] | None = None,
    *,
    exam_questions: list[dict[str, Any]] | None = None,
    digest_mode: str = "",
    review_prompts: list[str] | None = None,
) -> str:
    prompts = question_titles or ["整份文档"]
    mode_profile = get_docgen_mode_profile(digest_mode)
    questions = list(exam_questions or [])
    if not questions:
        questions = [
            {
                "question_index": index,
                "type": "short_answer",
                "question": f"请用自己的话解释《{title}》最重要的知识点，并补一个贴近本课程的例子或应用场景。",
            }
            for index, title in enumerate(prompts, start=1)
        ]

    if mode_profile.is_sprint:
        lines = ["# 练习与巩固", "", "## 典型任务/题型与例子", ""]
        for question in questions:
            lines.append(f"{int(question.get('question_index', 0) or 0) or 1}. {question.get('question', '')}")
        lines.extend(
            [
                "",
                "## 易错点辨析",
                "",
                *[f"- {item}" for item in (review_prompts or [
                    "哪个任务或题目你是靠感觉完成的？把它改成可复述的判断步骤。",
                    "哪一个结论你会背但还不会判断使用条件？",
                    "如果可用时间很紧，这份文档里你应该优先复习哪两章或哪两个任务场景？",
                ])],
            ]
        )
        return "\n".join(lines).strip() + "\n"

    lines = ["# 练习与巩固", "", "## 理解与推理题", ""]
    for question in questions:
        lines.append(f"{int(question.get('question_index', 0) or 0) or 1}. {question.get('question', '')}")
    lines.extend(
        [
            "",
            "## 综合迁移",
            "",
            *[f"- {item}" for item in (review_prompts or [
                "把一章里的核心定义、方法和例子串成一条完整主线。",
                "指出哪一个概念最容易和邻近概念混淆，并做一次对比辨析。",
                "尝试把这份文档中的一个方法迁移到一个新问题或新场景中。",
            ])],
        ]
    )
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "build_examine_markdown",
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
