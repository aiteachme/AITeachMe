"""撰写 & 质检阶段纯函数服务。"""

from __future__ import annotations

import json
import re

import structlog

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.workflows.digest.prompts.docgen_prompts import (
    METADATA_PROMPT,
    REVIEWER_PROMPT,
    TARGETED_REWRITE_PROMPT,
    WRITER_PROMPT,
)

logger = structlog.get_logger()

_SUMMARY_PAT = re.compile(r"^>\s*本章导学[:：]\s*(.+)$", re.MULTILINE)
_TAG_LINE_PAT = re.compile(r"^关键词[:：]\s*(.+)$", re.MULTILINE)
_H1_PAT = re.compile(r"^\s*#\s+.+$", re.MULTILINE)
_H2_PAT = re.compile(r"^\s*##\s+.+$", re.MULTILINE)
_FORMULA_PAT = re.compile(r"\$\$.*?\$\$|\$[^$\n]{2,160}\$", re.DOTALL)
_SPACE_PAT = re.compile(r"\s+")


def build_global_outline_summary(outline_tree: dict) -> str:
    """将目录树转为可读大纲文本。"""

    lines: list[str] = []
    for ch in outline_tree.get("chapters", []):
        lines.append(f"第{ch.get('chapter_index', '?')}章 {ch.get('title', '')}")
        for sec in ch.get("sections", []):
            lines.append(f"  - {sec.get('title', '')}")
    return "\n".join(lines)


def _normalize_tag(title: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "", title).strip()
    return f"#{cleaned[:12]}" if cleaned else "#核心知识"


def _compress_text(text: str, *, max_chars: int = 220) -> str:
    normalized = _SPACE_PAT.sub(" ", text.replace("\n", " ")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def _derive_summary(chapter_title: str, section_titles: list[str], formula_refs: list[str]) -> str:
    if section_titles:
        joined = "、".join(title.strip() for title in section_titles[:3] if title.strip())
        return f"本章围绕{joined}展开，帮助你建立关于{chapter_title}的核心框架与复习抓手。"
    if formula_refs:
        return f"本章围绕{chapter_title}的关键概念与公式展开，重点梳理公式含义、使用场景与常见误区。"
    return f"本章系统梳理{chapter_title}的核心内容，帮助你快速抓住重点、方法和考试常见切入点。"


def _derive_tags(chapter_title: str, section_titles: list[str], markdown: str | None = None) -> list[str]:
    candidates = [chapter_title, *section_titles]
    if markdown:
        for match in re.findall(r"^\s*##\s+(.+?)\s*$", markdown, flags=re.MULTILINE):
            candidates.append(match)

    tags: list[str] = []
    for candidate in candidates:
        tag = _normalize_tag(candidate)
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= 5:
            break
    return tags or ["#核心知识"]


def _normalize_formula_token(text: str) -> str:
    return _SPACE_PAT.sub("", text).replace("（", "(").replace("）", ")")


def _formula_coverage(markdown: str, formula_refs: list[str]) -> tuple[int, list[str]]:
    if not formula_refs:
        return 0, []

    markdown_token = _normalize_formula_token(markdown)
    missing: list[str] = []
    for formula in formula_refs:
        token = _normalize_formula_token(formula)
        if not token or token not in markdown_token:
            missing.append(formula)
    return len(formula_refs) - len(missing), missing


def _strip_extra_h1(markdown: str, chapter_title: str) -> str:
    lines = markdown.strip().splitlines()
    output: list[str] = []
    seen_h1 = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            if seen_h1:
                if stripped == f"# {chapter_title}":
                    continue
                output.append(f"## {stripped[2:].strip()}")
                continue
            output.append(f"# {chapter_title}")
            seen_h1 = True
            continue
        output.append(line)
    if not seen_h1:
        output.insert(0, f"# {chapter_title}")
        output.insert(1, "")
    return "\n".join(output).strip()


def _build_formula_section(formula_refs: list[str]) -> str:
    if not formula_refs:
        return ""
    lines = ["## 关键公式与结论", ""]
    for formula in formula_refs[:8]:
        lines.append(f"- `{formula}`")
    return "\n".join(lines).strip()


def _build_fallback_chapter(
    *,
    chapter_title: str,
    section_titles: list[str],
    source_content: str,
    formula_refs: list[str],
) -> str:
    summary = _derive_summary(chapter_title, section_titles, formula_refs)
    tags = " ".join(_derive_tags(chapter_title, section_titles))

    paragraphs = [segment.strip() for segment in source_content.split("\n\n") if segment.strip()]
    excerpt_blocks = paragraphs[:4]

    lines = [
        f"# {chapter_title}",
        "",
        f"> 本章导学：{summary}",
        "",
        "## 核心概念",
        "",
    ]

    if excerpt_blocks:
        for block in excerpt_blocks:
            lines.append(_compress_text(block, max_chars=260))
            lines.append("")
    else:
        lines.append("原始资料可用内容较少，本章建议结合源文件继续核对细节。")
        lines.append("")

    if formula_refs:
        lines.append(_build_formula_section(formula_refs))
        lines.append("")

    lines.extend([
        "## 复习抓手",
        "",
        "- 先看概念之间的关系，再记公式与使用条件。",
        "- 复习时优先回到关键定义、典型题型和常见误区。",
        "",
        f"关键词：{tags}",
    ])
    return "\n".join(lines).strip()


def normalize_chapter_markdown(
    *,
    markdown: str,
    chapter_title: str,
    section_titles: list[str],
    formula_refs: list[str],
) -> str:
    """统一章节骨架，避免结构不稳定。"""

    normalized = _strip_extra_h1(markdown or "", chapter_title)
    structure = analyze_chapter_structure(normalized)

    summary = _SUMMARY_PAT.search(normalized)
    if not summary:
        summary_text = _derive_summary(chapter_title, section_titles, formula_refs)
        normalized = normalized.replace(
            f"# {chapter_title}",
            f"# {chapter_title}\n\n> 本章导学：{summary_text}",
            1,
        )

    if not structure["has_sections"]:
        insert_block = "## 核心概念\n\n"
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[:3] + ["", insert_block] + lines[3:])
        else:
            normalized = f"{normalized}\n\n{insert_block}".strip()

    _, missing_formulas = _formula_coverage(normalized, formula_refs)
    if formula_refs and missing_formulas:
        formula_section = _build_formula_section(missing_formulas[:6])
        if "## 关键公式与结论" in normalized:
            normalized = f"{normalized}\n\n" + "\n".join(f"- `{formula}`" for formula in missing_formulas[:6])
        else:
            normalized = f"{normalized}\n\n{formula_section}".strip()

    tags_match = _TAG_LINE_PAT.search(normalized)
    if not tags_match:
        tags = " ".join(_derive_tags(chapter_title, section_titles, normalized))
        normalized = f"{normalized}\n\n关键词：{tags}".strip()

    return normalized.strip()


def assemble_chapter_from_sections(
    *,
    chapter_title: str,
    section_markdowns: list[str],
    section_titles: list[str],
) -> str:
    summary = _derive_summary(chapter_title, section_titles, [])
    tags = " ".join(_derive_tags(chapter_title, section_titles))
    body = "\n\n".join(markdown.strip() for markdown in section_markdowns if markdown.strip())
    lines = [
        f"# {chapter_title}",
        "",
        f"> 本章导学：{summary}",
        "",
        body or "## 核心概念\n\n暂无可用内容。",
        "",
        f"关键词：{tags}",
    ]
    return "\n".join(lines).strip()


async def write_section(
    *,
    chapter_title: str,
    section_title: str,
    section_index: int,
    total_sections: int,
    user_prompt: str | None,
    source_content: str,
) -> str:
    source_excerpt = source_content[:5000]
    prompt = f"""你是 AITeachMe 的教学讲义助手。请只撰写单个小节。

当前章节：{chapter_title}
当前小节：{section_title}
小节序号：{section_index}/{total_sections}
用户要求：{user_prompt or "（无额外要求）"}

原始素材：
{source_excerpt}

要求：
1. 直接从 `## {section_title}` 开始输出。
2. 用教学化语言重写，不要整段照抄。
3. 保留概念、方法、公式与典型例子。
4. 不要输出一级标题、导学或关键词。

请直接返回 Markdown。"""
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
        return result.strip()
    except Exception as exc:
        logger.warning(
            "write_section_failed",
            chapter_title=chapter_title,
            section_title=section_title,
            error=str(exc),
        )
        return f"## {section_title}\n\n{_compress_text(source_excerpt, max_chars=1200)}"


async def write_chapter(
    *,
    chapter_title: str,
    chapter_index: int,
    total_chapters: int,
    global_outline_text: str,
    section_titles: list[str],
    user_prompt: str | None,
    prev_summary: str,
    next_preview: str,
    source_brief: str,
    formula_refs: list[str],
    source_content: str,
) -> str:
    """调用 Writer Agent 撰写单章 Markdown。"""

    max_src = 18000
    truncated_content = source_content
    if len(truncated_content) > max_src:
        truncated_content = truncated_content[:max_src] + "\n\n（原始素材过长，以上为核心截取内容）"

    prompt = WRITER_PROMPT.format(
        global_outline=global_outline_text,
        chapter_title=chapter_title,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        section_titles="、".join(section_titles) or "（待归纳）",
        user_prompt=user_prompt or "（无额外要求）",
        prev_summary=prev_summary or "（上一章摘要为空）",
        formula_refs="\n".join(f"- {formula}" for formula in formula_refs[:8]) or "（本章未抽取到明确公式）",
        source_brief=source_brief or "（无额外导览）",
        source_content=truncated_content,
        next_preview=next_preview or "（没有下一章预告）",
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
        return normalize_chapter_markdown(
            markdown=result.strip(),
            chapter_title=chapter_title,
            section_titles=section_titles,
            formula_refs=formula_refs,
        )
    except Exception as exc:
        logger.error("write_chapter_failed", chapter_index=chapter_index, error=str(exc))
        return _build_fallback_chapter(
            chapter_title=chapter_title,
            section_titles=section_titles,
            source_content=truncated_content,
            formula_refs=formula_refs,
        )


async def review_chapter(markdown: str, source_summary: str, *, user_prompt: str | None = None) -> dict:
    """调用 Reviewer Agent 质检单章。"""

    prompt = REVIEWER_PROMPT.format(
        document=markdown[:8000],
        source_summary=source_summary[:2000],
        user_prompt=user_prompt or "（无额外要求）",
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception as exc:
        logger.warning("review_chapter_failed", error=str(exc))
        return {"passed": True, "issues": [], "suggestions": []}


def analyze_chapter_structure(markdown: str) -> dict[str, bool]:
    """检查章节是否满足关键结构要求。"""

    h1_count = len(_H1_PAT.findall(markdown))
    return {
        "has_single_h1": h1_count == 1,
        "has_summary": bool(_SUMMARY_PAT.search(markdown)),
        "has_tags": bool(_TAG_LINE_PAT.search(markdown)),
        "has_sections": bool(_H2_PAT.search(markdown)),
    }


def audit_chapter(
    *,
    markdown: str,
    chapter_title: str,
    section_titles: list[str],
    formula_refs: list[str],
) -> dict:
    """基于规则做快速质检，必要时再升级到 LLM。"""

    issues: list[str] = []
    suggestions: list[str] = []
    structure = analyze_chapter_structure(markdown)

    if not structure["has_single_h1"]:
        issues.append("一级标题数量不正确")
    if not structure["has_summary"]:
        issues.append("缺少本章导学")
    if not structure["has_sections"]:
        issues.append("缺少二级标题组织")
    if not structure["has_tags"]:
        issues.append("缺少关键词行")

    covered_formula_count, missing_formulas = _formula_coverage(markdown, formula_refs)
    if formula_refs and covered_formula_count == 0:
        issues.append("关键公式没有被纳入正文")
    elif missing_formulas:
        suggestions.append("补齐部分关键公式的解释或展示")

    if chapter_title not in markdown[:200]:
        suggestions.append("章节标题应在开头稳定呈现")
    if section_titles and len(markdown) < 900:
        suggestions.append("本章内容偏短，可能展开不够")

    needs_llm = any("公式" in issue for issue in issues) or len(issues) >= 2
    return {
        "passed": not issues,
        "issues": issues,
        "suggestions": suggestions,
        "needs_llm": needs_llm,
        "missing_formulas": missing_formulas[:6],
    }


def should_retry_review(*, markdown: str, review_result: dict) -> bool:
    """仅对硬失败触发定向修订。"""

    if review_result.get("passed", True):
        return False

    structure = analyze_chapter_structure(markdown)
    if not structure["has_single_h1"] or not structure["has_summary"] or not structure["has_tags"]:
        return True

    if review_result.get("needs_llm"):
        return True

    issue_text = " ".join(str(item) for item in review_result.get("issues", []))
    hard_keywords = ("一级标题", "本章导学", "关键词", "公式")
    return any(keyword in issue_text for keyword in hard_keywords)


async def revise_chapter_targeted(
    markdown: str,
    *,
    issues: list[str],
    source_summary: str,
    user_prompt: str | None = None,
) -> str:
    """对失败章节做定向修订，而不是整章重写。"""

    prompt = TARGETED_REWRITE_PROMPT.format(
        document=markdown[:12000],
        user_prompt=user_prompt or "（无额外要求）",
        source_summary=source_summary[:2000],
        issues="\n".join(f"- {item}" for item in issues) or "（未提供具体问题，请优先修补结构与公式）",
    )
    result = await acompletion(
        [{"role": "user", "content": prompt}],
        task_type=TaskType.DOCGEN_LIGHT,
    )
    return result.strip()


def extract_metadata_rule_based(markdown: str) -> dict:
    """优先从生成好的章节 Markdown 中抽取摘要与标签。"""

    summary_match = _SUMMARY_PAT.search(markdown)
    tag_match = _TAG_LINE_PAT.search(markdown)
    tags: list[str] = []
    if tag_match:
        tags = [tag for tag in tag_match.group(1).split() if tag.startswith("#")]
    if not tags:
        heading_titles = re.findall(r"^\s*##\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
        tags = _derive_tags("核心知识", heading_titles, markdown)
    return {
        "summary": summary_match.group(1).strip()[:200] if summary_match else "",
        "tags": tags[:5],
    }


async def extract_metadata(markdown: str) -> dict:
    """LLM 提取章节 summary + tags。"""

    prompt = METADATA_PROMPT.format(document=markdown[:3000])
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        meta = json.loads(cleaned)
        return {
            "summary": meta.get("summary", "")[:200],
            "tags": meta.get("tags", []),
        }
    except Exception as exc:
        logger.warning("extract_metadata_failed", error=str(exc))
        return {"summary": "", "tags": []}
