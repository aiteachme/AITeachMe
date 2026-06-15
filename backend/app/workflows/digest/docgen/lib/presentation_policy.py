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
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile

LEARNING_ROLE_LABELS = {
    "topic": "主题模块",
    "concept": "概念术语",
    "principle": "原理性质",
    "formula_model": "公式模型",
    "procedure": "方法步骤",
    "skill": "解题技能",
    "misconception": "易错辨析",
    "application_case": "应用案例",
    "resource": "学习资源",
}

RELATION_LABELS = {
    "part_of": "归属",
    "prerequisite_for": "前置",
    "derives_to": "推导",
    "applies_to": "应用",
    "uses_method": "用方法",
    "assesses": "考察",
    "explains": "解释",
    "remediates": "补救",
    "confuses_with": "易混",
    "similar_to": "相似",
    "extends_to": "拓展",
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
            "visual_grouping": "定义、公式、步骤、例题、易错点和高频规则清单要有清晰边界，避免连续大段正文把不同学习功能混在一起。",
            "formulas": "行内公式用 $...$，多步推导或长公式用 $$...$$，变量和适用条件要解释。",
            "code_blocks": "代码、配置、命令、伪代码必须使用 fenced code block 并标注语言。",
            "mermaid": "Mermaid 必须放在 ```mermaid 代码块；知识图谱关系标签只使用受控关系类型。",
            "html_sidecar": "交互内容只允许独立单文件 HTML sidecar，正文 Markdown 不内嵌任意 HTML。",
        },
        "reader_experience_checks": {
            "long_paragraphs": "避免连续长段正文；长解释要拆成步骤、表格、公式块、例题或短提示。",
            "learning_callout_fields": "例题和练习必须能自查，至少有题目/任务、解析/判定依据、答案/结论。",
            "reading_blocks": "长章节需要有短提示、表格、公式、图示、代码块或例题等阅读分组，避免整章只有正文和列表。",
            "list_rhythm": "长列表要拆分成小节、表格或练习块，避免学生扫读疲劳。",
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
    relation_text = "、".join(RELATION_LABELS.values())
    if profile.is_sprint:
        structure_line = "- 结构：`# 章节标题` -> 考点速览表（考点/重要程度/题型或任务/抓手） -> `## 01 短考点名`。"
        section_line = "- 紧凑节奏小节先讲具体方法或判断口径，再用例题、任务、解析结论和错因边界落地；标题按内容命名。"
    else:
        structure_line = "- 结构：`# 章节标题` -> 3-5 行导航表 -> `## 01 具体知识点名`。"
        section_line = "- 每个知识点小节包含解释、条件步骤、例题任务、解析结论和易错边界；标题按内容命名。"
    return f"""
Markdown 表达：
{structure_line}
- 二级标题写本章具体知识、方法、任务或场景；三级标题只服务同一小节下的并列子主题。
{section_line}
- 段落短，长列表改成表格、步骤或任务块；表格优先用于对比、分类、步骤和错因。
- 重点可加粗或少量高亮；callout 只放短提醒，例题和练习用普通正文块。
- 公式、代码、Mermaid 使用可渲染 Markdown；Mermaid 关系标签限：{relation_text}。
- 需要图形辅助时，正文写清题设、变量、几何/坐标/结构关系和图注，静态 HTML 图示节点会绘制 SVG。
- 图示优先服务只靠文字不直观的对象：几何条件、坐标图像、统计图、电路/结构/路径/区域或实验装置。
- {profile.prompt_label}：紧凑节奏重例题、任务和错误诊断；系统节奏重概念、推理和例子覆盖。
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


def summarize_docgen_presentation_collection(
    chapters: list[dict[str, Any]],
    *,
    merged_markdown: str = "",
    digest_mode: str = "",
) -> dict[str, object]:
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
        "policy": build_presentation_policy(digest_mode=digest_mode),
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
