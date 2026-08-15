"""Prompt builders for whole-document DocGen consistency review."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile

_MAX_LIST_ITEMS = 12


def _string_list(value: object, *, limit: int = _MAX_LIST_ITEMS) -> list[str]:
    raw = value if isinstance(value, list) else ([] if value is None else [value])
    items: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _heading_lines(markdown: str) -> list[str]:
    headings = [
        line.strip()
        for line in str(markdown or "").splitlines()
        if line.lstrip().startswith("#")
    ]
    return headings[:12]


def _compact_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in chapters:
        markdown = str(item.get("markdown") or "")
        compacted.append(
            {
                "chapter_index": item.get("chapter_index"),
                "title": item.get("title"),
                "word_count": item.get("word_count"),
                "source_count": len(list(item.get("source_details") or [])),
                "warnings": _string_list(item.get("warnings"), limit=8),
                "headings": _heading_lines(markdown),
                "markdown": markdown,
            }
        )
    return compacted


def _compact_guideline(guideline: dict[str, Any]) -> dict[str, Any]:
    return {
        "writing_rules": _string_list(guideline.get("writing_rules")),
        "canonical_glossary": [
            {
                "term": item.get("term"),
                "definition": item.get("definition"),
                "target_chapters": item.get("target_chapters"),
            }
            for item in list(guideline.get("canonical_glossary") or [])
            if isinstance(item, dict)
        ],
        "notation_rules": [
            {
                "symbol": item.get("symbol"),
                "meaning": item.get("meaning"),
                "target_chapters": item.get("target_chapters"),
            }
            for item in list(guideline.get("notation_rules") or [])
            if isinstance(item, dict)
        ],
        "confusion_checks": [
            {
                "pair": item.get("pair") or item.get("terms"),
                "check": item.get("check") or item.get("risk") or item.get("note"),
            }
            for item in list(guideline.get("confusion_checks") or [])
            if isinstance(item, dict)
        ],
    }


def _compact_dispatch(dispatch_table: dict[str, Any]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in list(dispatch_table.get("items") or []):
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "chapter_index": item.get("chapter_index"),
                "preferred_sources": _string_list(item.get("preferred_sources"), limit=8),
                "source_section_refs": _string_list(item.get("source_section_refs"), limit=8),
                "evidence_ids": _string_list(item.get("evidence_ids"), limit=8),
            }
        )
    return compacted


def _compact_rule_report(rule_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": bool(rule_report.get("passed", True)),
        "issues": list(rule_report.get("issues") or []),
        "glossary_warnings": _string_list(
            rule_report.get("glossary_warnings"),
            limit=max(_MAX_LIST_ITEMS, len(list(rule_report.get("glossary_warnings") or []))),
        ),
        "source_summary": dict(rule_report.get("source_summary") or {}),
    }


def build_document_review_messages(
    *,
    digest_mode: str,
    reviewed_chapters: list[dict[str, Any]],
    rule_report: dict[str, Any],
    guideline: dict[str, Any] | None = None,
    dispatch_table: dict[str, Any] | None = None,
    learner_profile_text: str = "",
) -> list[dict[str, str]]:
    """Build messages for a single whole-document structured review."""

    mode_profile = get_docgen_mode_profile(digest_mode)
    compact_chapters = _compact_chapters(reviewed_chapters)
    compact_guideline = _compact_guideline(dict(guideline or {}))
    compact_dispatch = _compact_dispatch(dict(dispatch_table or {}))
    compact_rule_report = _compact_rule_report(dict(rule_report or {}))
    learner_context = str(learner_profile_text or "").strip()
    system_prompt = """
你是 AITeachMe 的整本文档复核器，只做跨章一致性判断。
你不能改写正文，不能润色措辞，不能要求推翻用户已确认的大纲；只输出确有风险的问题和可执行回流动作。
问题必须影响学习正确性、跨章一致性、证据边界、后续考试/画像可用性或发布结构，普通风格偏好不要输出。
章末题目、正文例题及其答案和题解的正确性是最高优先级；必须独立解题校验，不能只检查格式，也不能默认文档给出的答案正确。
""".strip()
    user_prompt = f"""
请对整本课程文档做最后一次结构化复核。

文档模式：{mode_profile.prompt_label}

规则复核基线：
{compact_rule_report}

全局 guideline：
{compact_guideline}

章节资料分配：
{compact_dispatch}

学习者画像补充：
{learner_context!r}

章节快照：
{compact_chapters}

复核要求：
1. 重点检查跨章术语、符号、定义、前置关系、重复讲解、互相矛盾、章节边界漂移和未解释跳步。
2. 检查每章与 dispatch/guideline 是否一致：不要把只属于其它章节的资料、例题或结论扩成当前章主体。
3. 对每道章末题和正文例题先遮住现有答案再独立作答：确认题干条件足够、答案可唯一推出；选择题的标记答案确实属于选项，干扰项不重复、不等价且不能同时成立。
4. 逐步核对题解：每一步推理、计算、符号、定义域、边界、单位和充分/必要条件都成立，题解最终结论与给定答案一致。发现歧义、错解、答案与选项不符或无法由本章材料确认时，必须对该章 `单元测试`/对应例题输出 `section_patch`，不得仅记录 warning 后放行。
5. 检查是否能承接 examine/profile：核心概念、方法、易错点、题型/任务和章末练习是否足够结构化，是否存在无法被考试链路定位的空泛段落。
6. 只输出真实问题。不要因为想更优雅、更多例子或更长篇幅而输出 action。
7. 局部章节问题用 `section_patch` 或 `evidence_patch`，必须带 `chapter_index` 和 `target_anchor`。
8. 纯记录或后续观察用 `record_only`；资料分配明显错用 `re_dispatch`；全局术语/符号骨架明显冲突才用 `rebuild_backbone`。
9. 不要在 instruction 里直接写可复制的新标题或完整正文；只描述需要修复的学习问题、约束和预期效果。
10. 如果没有影响正确性或学习闭环的问题，返回 passed=true、issues=[]、actions=[]。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "document_review",
        inputs={
            "digest_mode": digest_mode,
            "chapter_count": len(reviewed_chapters),
            "scoped_chapter_count": len(compact_chapters),
            "rule_issue_count": len(compact_rule_report["issues"]),
            "guideline_term_count": len(compact_guideline["canonical_glossary"]),
            "dispatch_item_count": len(compact_dispatch),
        },
        output=messages,
    )


__all__ = ["build_document_review_messages"]
