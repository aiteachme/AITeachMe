"""Prompt builders for DocGen content review."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

_MAX_REVIEW_MARKDOWN_CHARS = 12000
_MAX_REVIEW_LIST_ITEMS = 12


def _trim_text(value: object, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    head_len = max_chars * 2 // 3
    tail_len = max_chars - head_len
    return f"{text[:head_len].rstrip()}\n\n[...中间内容已截断，复核范围仍限于本章...]\n\n{text[-tail_len:].lstrip()}"


def _string_list(values: object, *, limit: int = _MAX_REVIEW_LIST_ITEMS) -> list[str]:
    raw_items = values if isinstance(values, list) else ([] if values is None else [values])
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
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


def _compact_task(task: dict[str, Any]) -> dict[str, Any]:
    raw_practice_seed_policy = task.get("practice_seed_policy")
    practice_seed_policy = raw_practice_seed_policy if isinstance(raw_practice_seed_policy, dict) else {}
    return {
        "chapter_index": task.get("chapter_index"),
        "confirmed_title": task.get("confirmed_title"),
        "enhanced_title": task.get("enhanced_title"),
        "objective": task.get("objective"),
        "required_elements": _string_list(task.get("required_elements")),
        "content_points": _string_list(task.get("content_points")),
        "concept_targets": _string_list(task.get("concept_targets")),
        "definition_targets": _string_list(task.get("definition_targets")),
        "formula_targets": _string_list(task.get("formula_targets")),
        "example_targets": _string_list(task.get("example_targets")),
        "pitfall_targets": _string_list(task.get("pitfall_targets")),
        "claim_targets": _string_list(task.get("claim_targets")),
        "forbidden_scope": _string_list(task.get("forbidden_scope"), limit=8),
        "min_word_count": task.get("min_word_count"),
        "target_word_count": task.get("target_word_count"),
        "coverage_threshold": task.get("coverage_threshold"),
        "evidence_support_threshold": task.get("evidence_support_threshold"),
        "example_coverage_plan": list(task.get("example_coverage_plan") or [])[:_MAX_REVIEW_LIST_ITEMS],
        "practice_seed_policy": {
            "digest_mode": practice_seed_policy.get("digest_mode"),
            "example_density_policy": practice_seed_policy.get("example_density_policy"),
            "content_mix_policy": practice_seed_policy.get("content_mix_policy"),
        },
    }


def _compact_claim_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in list(ledger.get("items") or [])[:_MAX_REVIEW_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "claim_id": item.get("claim_id"),
                "claim_text": item.get("claim_text"),
                "claim_type": item.get("claim_type"),
                "requires_evidence": item.get("requires_evidence"),
                "evidence_ids": _string_list(item.get("evidence_ids"), limit=6),
            }
        )
    return {
        "chapter_index": ledger.get("chapter_index"),
        "claim_count": len(list(ledger.get("items") or [])),
        "fallback_used": bool(ledger.get("fallback_used", False)),
        "claims": items,
    }


def _compact_claim_evidence_map(mapping: dict[str, Any]) -> dict[str, Any]:
    raw_bindings = [item for item in list(mapping.get("bindings") or []) if isinstance(item, dict)]

    def _support_level(item: dict[str, Any]) -> float:
        try:
            return float(item.get("support_level") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    low_support = [
        item
        for item in raw_bindings
        if _support_level(item) < 0.55
    ]
    return {
        "chapter_index": mapping.get("chapter_index"),
        "binding_count": len(raw_bindings),
        "low_support_bindings": [
            {
                "claim_id": item.get("claim_id"),
                "evidence_ids": _string_list(item.get("evidence_ids"), limit=6),
                "support_level": item.get("support_level"),
                "notes": item.get("notes"),
            }
            for item in low_support[:_MAX_REVIEW_LIST_ITEMS]
        ],
        "fallback_used": bool(mapping.get("fallback_used", False)),
    }


def _compact_conflict_report(report: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in list(report.get("items") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("severity") or "") not in {"warning", "error"}:
            continue
        items.append(
            {
                "conflict_type": item.get("conflict_type"),
                "severity": item.get("severity"),
                "detail": item.get("detail"),
                "resolution": item.get("resolution"),
            }
        )
        if len(items) >= _MAX_REVIEW_LIST_ITEMS:
            break
    return {
        "chapter_index": report.get("chapter_index"),
        "unresolved_count": report.get("unresolved_count"),
        "conflicts": items,
        "fallback_used": bool(report.get("fallback_used", False)),
    }


def build_chapter_review_messages(
    *,
    chapter_title: str,
    digest_mode: str,
    chapter_task: dict,
    markdown: str,
    claim_ledger: dict,
    claim_evidence_map: dict,
    conflict_report: dict,
    rule_review: dict,
) -> list[dict[str, str]]:
    """Build messages for read-only chapter review."""

    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    compact_task = _compact_task(chapter_task)
    compact_claim_ledger = _compact_claim_ledger(claim_ledger)
    compact_claim_evidence_map = _compact_claim_evidence_map(claim_evidence_map)
    compact_conflict_report = _compact_conflict_report(conflict_report)
    scoped_markdown = _trim_text(markdown, max_chars=_MAX_REVIEW_MARKDOWN_CHARS)
    system_prompt = """
你是 AITeachMe 的内容质检员，只负责复核，不负责改写。
你必须严格检查章节是否符合用户已确认的学习大纲、是否有证据支撑、是否越界、是否适合学习。
你不能新增事实，不能替正文打补丁，不能要求推翻已确认计划。
如果问题可以局部修，输出 action_type 为 `section_patch` 或 `evidence_patch`；只有整章严重不可用时才输出 `regenerate_chapter`。
证据不足时优先输出 action_type 为 `evidence_patch`，不要轻易要求整章重写。
""".strip()
    user_prompt = f"""
请复核下面这一章，并输出结构化结果。

章节标题：{chapter_title}
文档模式：{mode_label}

章节执行合同：
{compact_task}

规则复核基线：
{rule_review}

本章主张摘要：
{compact_claim_ledger}

低支撑证据绑定：
{compact_claim_evidence_map}

冲突报告：
{compact_conflict_report}

章节 Markdown：
{scoped_markdown}

复核要求：
1. 判断是否覆盖执行合同中的关键点。
2. 判断主张是否有足够证据支撑。
3. 判断是否越过章节边界或推翻已确认计划。
4. 判断是否适合学生学习，不要只看格式。
5. 检查 7 类学习内容角色是否按学习大纲合理覆盖：核心知识、方法示范、解释辅助、原理推理、练习评估、知识组织、应用拓展。
6. 如果是快速复习节奏，重点检查例题、案例、变式、自测或实践任务是否足够支撑“会做题/会操作/会判断/会避坑”；例题密度不足时输出 `section_patch`。
7. 如果是快速复习节奏，还要检查是否有由本章内容自然生成的题型或任务整理、条件与方法速查、例题解析、变式/自测和易错复盘；具体标题、表头和条目应来自章节语义，不应像固定口号或本地模板。
8. 如果是系统课，重点检查核心知识点是否都有例题、案例、操作示例或练习任务覆盖；知识点缺少例题覆盖时输出 `section_patch`。
9. 检查展示质量：标题层级、加粗/高亮闭合、callout、表格、公式、代码块、Mermaid 是否可渲染；纯格式问题输出 `surface_patch`，不要升级为整章重写。
10. 检查知识图谱相关内容是否只使用 7 类学习节点与 8 类关系；关系方向明显错误时输出 `section_patch`。
11. 复核动作必须可执行，写清 `target_anchor`、`instruction`、`constraints`、`expected_effect`。
12. 只做复核判断，不输出修补后的正文。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "chapter_review",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "markdown_chars": len(markdown),
            "scoped_markdown_chars": len(scoped_markdown),
            "chapter_task_keys": sorted(compact_task.keys()),
            "claim_count": compact_claim_ledger["claim_count"],
            "low_support_binding_count": len(compact_claim_evidence_map["low_support_bindings"]),
        },
        output=messages,
    )


__all__ = ["build_chapter_review_messages"]
