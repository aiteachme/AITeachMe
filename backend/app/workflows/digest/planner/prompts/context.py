"""Tiny text renderers shared by planner prompts.

这里不做规划判断，只把 workflow state 里的上下文转成 prompt 文本。
保留这一层是为了避免三个 prompt 文件重复拼接资料、历史和上一版方案。
"""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext

EMPTY_DIGEST = "暂无资料正文上下文"
EMPTY_HISTORY = "暂无补充意见"
EMPTY_LATEST_PLAN = "暂无上一版方案"
EMPTY_FILES = "暂无已解析文件"
EMPTY_EXISTING_DOC = "暂无已发布知识文档"
NO_MATERIAL_NOTE = "资料状态：当前没有可用的上传资料正文，只能基于用户提示生成通用初步计划，不能假装已经读取了具体文件。"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def render_material_digest(material_context: DigestMaterialContext) -> str:
    return _clean(material_context.material_digest) or f"{EMPTY_DIGEST}；{NO_MATERIAL_NOTE}"


def render_material_overview(material_context: DigestMaterialContext) -> str:
    profile = material_context.learning_domain_profile.build_context_string()
    files: list[str] = []
    for doc in material_context.source_documents:
        filename = _clean(doc.filename)
        if filename:
            files.append(filename)

    stats = material_context.material_stats_profile.stats
    lines = [
        profile,
        f"资料文件：{'、'.join(files) if files else EMPTY_FILES}",
        f"资料规模：{stats.total_sources or len(material_context.source_documents)} 个文件，"
        f"{stats.total_sections or len(material_context.material_sections)} 个片段",
    ]
    if not files and not _clean(material_context.material_digest):
        lines.append(NO_MATERIAL_NOTE)
    return "\n".join(line for line in lines if line.strip())


def render_message_history(message_history: list[str] | None, *, limit: int | None = None) -> str:
    history = [_clean(item) for item in message_history or [] if _clean(item)]
    selected = history[-limit:] if limit is not None and limit > 0 else history
    return "\n".join(f"- {item}" for item in selected) if selected else EMPTY_HISTORY


def render_latest_plan(latest_plan: dict[str, Any] | None) -> str:
    if not latest_plan:
        return EMPTY_LATEST_PLAN
    plan_summary = _clean(latest_plan.get("plan_summary"))
    chapter_count = len(list(latest_plan.get("chapter_plan") or []))
    step_count = len(list(latest_plan.get("plan_steps") or []))
    lines = [f"上一版摘要：{plan_summary}"] if plan_summary else []
    if step_count:
        lines.append(f"上一版计划步骤数：{step_count}")
    lines.append(f"上一版章节数：{chapter_count}")
    return "\n".join(lines)


def render_existing_doc_context(existing_doc_context: str | None) -> str:
    return _clean(existing_doc_context) or EMPTY_EXISTING_DOC


def render_planner_context_mode(*, planner_context_mode: str, existing_doc_context: str | None) -> str:
    if planner_context_mode == "rebuild_existing_doc" and _clean(existing_doc_context):
        return "\n".join(
            [
                "当前规划模式：已有知识文档重建/调整",
                "",
                "现有文档摘要：",
                render_existing_doc_context(existing_doc_context),
            ]
        )
    return "当前规划模式：新建知识文档"


__all__ = [
    "render_existing_doc_context",
    "render_latest_plan",
    "render_material_digest",
    "render_material_overview",
    "render_message_history",
    "render_planner_context_mode",
]
