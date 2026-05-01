"""DocGen presentation policy and deterministic presentation checks."""

from __future__ import annotations

from typing import Any

from app.shared.infra.tools.builtin.markdown_processing import (
    find_markdown_presentation_issues,
    normalize_markdown_rendering,
    normalize_mermaid_blocks,
    summarize_markdown_presentation,
)
from app.workflows.digest.docgen.lib.textbook_style import (
    normalize_educational_callouts,
    normalize_textbook_headings,
)
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

LEARNING_ROLE_LABELS = {
    "core_knowledge": "核心知识",
    "method_demo": "方法示范",
    "explanation_support": "解释辅助",
    "principle_reasoning": "原理推理",
    "practice_assessment": "练习评估",
    "knowledge_organization": "知识组织",
    "application_extension": "应用拓展",
}

RELATION_LABELS = {
    "prerequisite": "前置",
    "contains": "包含",
    "reasoning": "推理",
    "application": "应用",
    "explanation": "说明",
    "training": "训练",
    "contrast": "对比",
    "similar": "相似",
}


def build_presentation_policy(*, digest_mode: str = "") -> dict[str, Any]:
    """Return the stable student-facing style contract used by DocGen."""

    profile = get_docgen_mode_profile(digest_mode)
    return {
        "schema_version": 1,
        "source": "docgen.presentation_policy",
        "digest_mode": profile.mode,
        "markdown": {
            "heading_levels": "一级标题只用于章节标题，二/三级标题按内容层级展开，不跳级。",
            "emphasis": "核心概念、关键条件、结论、易错边界可加粗；不要整段加粗。",
            "highlight": "只对短关键句使用 ==...== 或受控 <mark>...</mark>，不要大量高亮。",
            "callouts": ["NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"],
            "tables": "表格用于对比、分类、步骤、公式汇总、错因分析和学习路径；建议 3-5 列。",
            "formulas": "行内公式用 $...$，多步推导或长公式用 $$...$$，变量和适用条件要解释。",
            "code_blocks": "代码、配置、命令、伪代码必须使用 fenced code block 并标注语言。",
            "mermaid": "Mermaid 必须放在 ```mermaid 代码块；知识图谱关系标签只使用 8 类关系。",
            "html_sidecar": "交互内容只允许独立单文件 HTML sidecar，正文 Markdown 不内嵌任意 HTML。",
        },
        "learning_roles": LEARNING_ROLE_LABELS,
        "relation_labels": RELATION_LABELS,
        "mode_focus": {
            "prompt_label": profile.prompt_label,
            "example_density_policy": dict(profile.example_density_policy),
            "content_mix_policy": dict(profile.content_mix_policy),
            "coverage_policy": list(profile.coverage_policy),
        },
    }


def build_presentation_contract_prompt(*, digest_mode: str = "") -> str:
    """Compact prompt fragment distilled from the full style/check specs."""

    profile = get_docgen_mode_profile(digest_mode)
    role_text = "、".join(LEARNING_ROLE_LABELS.values())
    relation_text = "、".join(RELATION_LABELS.values())
    return f"""
使用清晰、美观、可渲染的 Markdown。样式服务学习，不做纯装饰。

结构：
- 一级标题只用于章节标题，二级/三级标题按内容自然展开，不跳级，不写内部流程名。
- 文档按学习功能自然覆盖：{role_text}；这些是检查维度，不要求固定作为标题。
- {profile.prompt_label}模式下仍要遵守当前章节合同：速成型强调例题/任务/错误诊断密度，系统型强调知识细讲和例题覆盖。

重点表达：
- 核心概念、关键结论、适用条件、易错边界可加粗；不要整段加粗。
- 关键短句可以少量使用 `==重点==` 或 `<mark>重点</mark>`；高亮必须短、少、准。
- 可以适度使用 emoji 增强主模块可读性，但不要在每句话、提示块正文开头或公式/代码附近使用。

可渲染组件：
- 对比、分类、步骤、公式汇总、错因分析优先用 3-5 列 Markdown 表格。
- 教学提示块使用 `> [!IMPORTANT]` / `> [!TIP]` / `> [!WARNING]` / `> [!NOTE]` / `> [!CAUTION]`，每章只在真正关键处使用。
- 公式必须成对闭合：短公式 `$...$`，长推导 `$$...$$`；变量和适用条件要解释。
- 代码、命令、配置、伪代码必须使用带语言名的 fenced code block。
- Mermaid 必须使用 ```mermaid 代码块；若表达知识图谱，关系标签只使用：{relation_text}。
- 不在正文 Markdown 中使用任意 HTML 或内联样式；交互内容只能作为独立 HTML sidecar。
""".strip()


def normalize_docgen_presentation(
    markdown: str,
    *,
    digest_mode: str = "",
    title: str = "",
    focus_items: list[str] | None = None,
) -> str:
    """Run the deterministic presentation normalizers used at DocGen boundaries."""

    cleaned = normalize_mermaid_blocks(normalize_markdown_rendering(markdown))
    cleaned = normalize_textbook_headings(
        cleaned,
        digest_mode=digest_mode,
        fallback_title=title,
        focus_items=focus_items or [],
    )
    cleaned = normalize_educational_callouts(cleaned)
    cleaned = normalize_markdown_rendering(cleaned)
    return cleaned


def find_docgen_presentation_issues(markdown: str) -> list[str]:
    return find_markdown_presentation_issues(markdown)


def summarize_docgen_presentation(markdown: str) -> dict[str, object]:
    return summarize_markdown_presentation(markdown)


def summarize_docgen_presentation_collection(chapters: list[dict[str, Any]], *, merged_markdown: str = "") -> dict[str, object]:
    chapter_summaries = [
        {
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "title": str(chapter.get("title") or chapter.get("resolved_title") or ""),
            **summarize_docgen_presentation(str(chapter.get("markdown") or "")),
        }
        for chapter in chapters
    ]
    all_issues = [
        issue
        for summary in chapter_summaries
        for issue in list(summary.get("issues") or [])
        if str(issue).strip()
    ]
    merged_summary = summarize_docgen_presentation(merged_markdown) if merged_markdown else {}
    return {
        "policy": build_presentation_policy(),
        "chapter_count": len(chapter_summaries),
        "chapter_issue_count": sum(int(summary.get("issue_count", 0) or 0) for summary in chapter_summaries),
        "merged_issue_count": int(merged_summary.get("issue_count", 0) or 0),
        "top_issues": list(dict.fromkeys(all_issues))[:20],
        "chapters": chapter_summaries,
        "merged": merged_summary,
    }


__all__ = [
    "build_presentation_contract_prompt",
    "build_presentation_policy",
    "find_docgen_presentation_issues",
    "normalize_docgen_presentation",
    "summarize_docgen_presentation",
    "summarize_docgen_presentation_collection",
]
