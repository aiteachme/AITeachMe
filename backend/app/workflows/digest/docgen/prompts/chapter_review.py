"""Prompt builders for DocGen content review."""

from __future__ import annotations

from typing import Any

from app.models.knowledge_taxonomy import KNOWLEDGE_RELATION_TYPE_LABELS, KNOWLEDGE_UNIT_TYPE_LABELS
from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile

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
        "chapter_end_practice_plan": list(task.get("chapter_end_practice_plan") or [])[:8],
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


def _compact_guideline(guideline: dict[str, Any]) -> dict[str, Any]:
    return {
        "writing_rules": _string_list(guideline.get("writing_rules")),
        "canonical_glossary": [
            {
                "term": item.get("term"),
                "definition": item.get("definition"),
                "target_chapters": item.get("target_chapters"),
            }
            for item in list(guideline.get("canonical_glossary") or [])[:8]
            if isinstance(item, dict)
        ],
        "notation_rules": [
            {
                "symbol": item.get("symbol"),
                "meaning": item.get("meaning"),
            }
            for item in list(guideline.get("notation_rules") or [])[:6]
            if isinstance(item, dict)
        ],
        "confusion_checks": [
            {
                "pair": item.get("pair") or item.get("terms"),
                "check": item.get("check") or item.get("risk") or item.get("note"),
            }
            for item in list(guideline.get("confusion_checks") or [])[:6]
            if isinstance(item, dict)
        ],
        "global_claim_count": guideline.get("global_claim_count") or guideline.get("claim_count"),
    }


def _compact_dispatch_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chapter_index": item.get("chapter_index"),
        "preferred_sources": _string_list(item.get("preferred_sources"), limit=8),
        "source_section_refs": _string_list(item.get("source_section_refs"), limit=8),
        "evidence_ids": _string_list(item.get("evidence_ids"), limit=8),
        "source_slices": [
            {
                "section_ref": raw.get("section_ref"),
                "section_title": raw.get("section_title") or raw.get("header_path"),
                "summary": raw.get("summary") or raw.get("excerpt"),
            }
            for raw in list(item.get("source_slices") or [])[:8]
            if isinstance(raw, dict)
        ],
    }


def _compact_chapter_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "chapter_index": contract.get("chapter_index"),
        "title": contract.get("title") or contract.get("confirmed_title") or contract.get("enhanced_title"),
        "learning_objective": contract.get("learning_objective") or contract.get("objective"),
        "required_elements": _string_list(contract.get("required_elements") or contract.get("content_points")),
        "evidence_ids": _string_list(contract.get("evidence_ids"), limit=8),
        "teaching_outline": _string_list(contract.get("teaching_outline"), limit=8),
    }


def _compact_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "evidence_id": item.get("evidence_id"),
                "text": _trim_text(item.get("text"), max_chars=240),
                "source_title": item.get("source_title"),
                "source_ref": item.get("source_ref"),
                "confidence": item.get("confidence"),
            }
        )
    return compacted


def _taxonomy_label_text() -> str:
    unit_labels = "、".join(KNOWLEDGE_UNIT_TYPE_LABELS.values())
    relation_labels = "、".join(KNOWLEDGE_RELATION_TYPE_LABELS.values())
    return f"节点类型：{unit_labels}；关系类型：{relation_labels}"


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
    guideline_summary: dict | None = None,
    dispatch_item: dict | None = None,
    chapter_contract: dict | None = None,
    evidence_items: list[dict] | None = None,
    learner_profile_text: str = "",
) -> list[dict[str, str]]:
    """Build messages for read-only chapter review."""

    mode_profile = get_docgen_mode_profile(digest_mode)
    mode_label = mode_profile.prompt_label
    density_policy = dict(mode_profile.example_density_policy)
    chapter_end_min_tasks = int(density_policy.get("chapter_end_practice_min_tasks", 2) or 2)
    chapter_end_max_tasks = max(
        chapter_end_min_tasks,
        int(density_policy.get("chapter_end_practice_max_tasks", 4) or 4),
    )
    compact_task = _compact_task(chapter_task)
    compact_claim_ledger = _compact_claim_ledger(claim_ledger)
    compact_claim_evidence_map = _compact_claim_evidence_map(claim_evidence_map)
    compact_conflict_report = _compact_conflict_report(conflict_report)
    compact_guideline = _compact_guideline(dict(guideline_summary or {}))
    compact_dispatch = _compact_dispatch_item(dict(dispatch_item or {}))
    compact_chapter_contract = _compact_chapter_contract(dict(chapter_contract or {}))
    compact_evidence_items = _compact_evidence_items(list(evidence_items or []))
    scoped_markdown = _trim_text(markdown, max_chars=_MAX_REVIEW_MARKDOWN_CHARS)
    taxonomy_text = _taxonomy_label_text()
    learner_profile_excerpt = _trim_text(learner_profile_text, max_chars=1200)
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

DocGen 全局一致性上下文：
{{
  "guideline": {compact_guideline},
  "dispatch": {compact_dispatch},
  "chapter_contract": {compact_chapter_contract},
  "high_confidence_evidence": {compact_evidence_items},
  "learner_profile": {learner_profile_excerpt!r}
}}

章节 Markdown：
{scoped_markdown}

复核要求：
1. 同时检查覆盖、证据、边界和学习价值：是否覆盖执行合同，主张是否有支撑，是否越界或推翻已确认计划。
2. `forbidden_scope` 是其它章节的主题边界。除非正文只用一句话做前后联系，否则不得要求把 forbidden_scope 中的主题补成独立小节、例题、练习或标题。
3. 紧凑节奏要看章节角色：训练取向章节应有紧凑题型/任务导航、方法对照、完整例题、变式或自测；概念型章节应有短例子、反例、条件辨析或小任务。缺失时输出 `section_patch`。
4. 每个主要 `##` 必须像完整学习单元：讲清本小节对象、关键条件或边界、解释依据或处理路径，并至少有例子、任务、反例、操作检查或诊断标准之一；如果只是提纲式短句、名词堆叠或结论堆叠，输出 `section_patch`。
5. 每章最后一个二级标题必须固定为 `## 单元测试`，这是唯一固定标题；其它二级标题必须按本章内容自然命名。`## 单元测试` 中紧凑节奏通常 {chapter_end_min_tasks}-{chapter_end_max_tasks} 个短题/任务，系统节奏通常 2-4 个更深的案例检查、操作任务、边界辨析或迁移任务。每题必须使用独立的 `> [!QUESTION]` 题干块，并紧跟独立的 `> [!ANSWER]` 答案块，把答案、判定依据和解析放入 ANSWER 块；缺失、位置不是最后、无答案、答案未折叠或与本章不贴合时输出 `section_patch`。
6. 自测、辨析或思考题必须有参考答案、判定依据、解析步骤或结论；系统课核心知识点也要有例题、案例、操作示例或练习任务支撑。
7. 检查展示质量：标题层级、加粗/高亮闭合、callout、表格、公式、代码块、Mermaid 是否可渲染。例题/练习 callout 中的“题目/任务、解析/判定依据、答案/结论、易错点”必须分段或列表展示，不能挤在同一段。孤立三级标题属于层级过度切分，应要求合并成更具体的 `##` 或改成正文加粗小节。
8. 检查知识图谱相关内容是否只使用系统标准学习节点与关系类型，中文类型如下：{taxonomy_text}；关系方向明显错误时输出 `section_patch`。
9. 如果要求新增或改写小节，不要在 action 里给可直接复制的标题；只说明这个小节要解决什么学习问题，并要求修复模型按本章具体对象、方法、任务差异或场景命名。不要建议目录里看不出内容的泛标题、学习动作标题、内部检查标题或序号占位题型。
10. 复核动作必须可执行，写清 `target_anchor`、`instruction`、`constraints`、`expected_effect`；只做复核判断，不输出修补后的正文。
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
            "guideline_term_count": len(compact_guideline["canonical_glossary"]),
            "dispatch_source_slice_count": len(compact_dispatch["source_slices"]),
            "evidence_item_count": len(compact_evidence_items),
        },
        output=messages,
    )


__all__ = ["build_chapter_review_messages"]
