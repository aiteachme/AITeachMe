"""Course-level learning context snapshot helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.models.knowledge_doc import KnowledgeDoc
from app.models.course import Course
from app.utils.time import utcnow
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

_MAX_INTENT_TEXT_CHARS = 4000
_MAX_INTRO_TEXT_CHARS = 1200
_MAX_LLM_CONTEXT_CHARS = 16000
_MAX_SUMMARY_TEXT_CHARS = 900
_MAX_LIST_ITEMS = 12
_CHAPTER_PLAN_CONTAINERS = ("chapter_generation_plan", "chapter_generation_plan_seed")
_CHAPTER_LIST_FIELDS = (
    ("teaching_outline", 10, 180),
    ("content_points", 10, 180),
    ("concept_targets", 10, 120),
    ("definition_targets", 8, 120),
    ("formula_targets", 8, 120),
    ("example_targets", 8, 120),
    ("pitfall_targets", 8, 140),
)
_LEARNING_NODE_TYPES = {
    "core_knowledge": "核心知识",
    "method_demo": "方法示范",
    "explanation_support": "解释辅助",
    "principle_reasoning": "原理推理",
    "practice_assessment": "练习评估",
    "knowledge_organization": "知识组织",
    "application_extension": "应用拓展",
}
_LEARNING_EDGE_TYPES = {
    "prerequisite": "前置",
    "contains": "包含",
    "reasoning": "推理",
    "application": "应用",
    "explanation": "说明",
    "training": "训练",
    "contrast": "对比",
    "similar": "相似",
}


def _clean_text(value: Any, *, max_chars: int | None = None) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        return cleaned[: max(0, max_chars - 3)].rstrip() + "..."
    return cleaned


def _clean_multiline_text(value: Any, *, max_chars: int | None = None) -> str:
    cleaned_lines = [
        cleaned
        for line in str(value or "").splitlines()
        if (cleaned := _clean_text(line))
    ]
    cleaned = "\n".join(cleaned_lines).strip()
    if max_chars is not None:
        return _truncate_text(cleaned, max_chars=max_chars)
    return cleaned


def _truncate_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_chars:
        return text[: max(0, max_chars - 3)].rstrip() + "..."
    return text


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_items(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [] if value is None else [value]


def _mapping_items(value: Any, *, limit: int | None = None) -> list[dict[str, Any]]:
    items = [dict(item) for item in _as_items(value) if isinstance(item, Mapping)]
    return items[:limit] if limit is not None else items


def _safe_int(value: Any, *, default: int = 0, min_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None and parsed < min_value:
        return min_value
    return parsed


def _clean_string_list(value: Any, *, limit: int = _MAX_LIST_ITEMS, max_chars: int = 120) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in _as_items(value):
        text = _clean_text(item, max_chars=max_chars)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_int_list(value: Any, *, limit: int = _MAX_LIST_ITEMS) -> list[int]:
    cleaned: list[int] = []
    seen: set[int] = set()
    for item in _as_items(value):
        parsed = _safe_int(item)
        if parsed <= 0 or parsed in seen:
            continue
        seen.add(parsed)
        cleaned.append(parsed)
        if len(cleaned) >= limit:
            break
    return cleaned


def _normalize_learning_goal(value: Any, *, max_chars: int = 700) -> str:
    text = _clean_text(value, max_chars=max_chars)
    prefixes = (
        "长期学习意图：",
        "长期学习意图:",
        "用户学习意图：",
        "用户学习意图:",
        "用户意图是：",
        "用户意图是:",
        "用户意图是",
        "用户希望：",
        "用户希望:",
        "用户希望",
    )
    changed = True
    while changed and text:
        changed = False
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
    return _clean_text(text, max_chars=max_chars)


def _load_json_list(raw: str | None) -> list[Any]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _extract_chapter_index(value: Mapping[str, Any], fallback: int) -> int:
    return _safe_int(value.get("chapter_index", fallback) or fallback, default=fallback, min_value=1)


def _merge_chapter_payload(
    lookup: dict[int, dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    fallback_index: int,
) -> None:
    chapter_index = _extract_chapter_index(payload, fallback_index)
    lookup[chapter_index] = {**lookup.get(chapter_index, {}), **dict(payload)}


def _chapter_plan_lookup(docgen_artifacts: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    lookup: dict[int, dict[str, Any]] = {}
    for container_key in _CHAPTER_PLAN_CONTAINERS:
        chapters = _as_mapping(docgen_artifacts.get(container_key)).get("chapters")
        for index, payload in enumerate(_mapping_items(chapters), start=1):
            _merge_chapter_payload(lookup, payload, fallback_index=index)
    for index, payload in enumerate(_mapping_items(docgen_artifacts.get("chapter_task_seeds")), start=1):
        _merge_chapter_payload(lookup, payload, fallback_index=index)
    return lookup


def _document_backbone_snapshot(docgen_artifacts: Mapping[str, Any]) -> dict[str, Any]:
    backbone = _as_mapping(docgen_artifacts.get("document_backbone_snapshot"))
    return {
        "role": "docgen_learning_backbone",
        "description": "写作骨架与候选知识线索，不是已验证知识图谱。",
        "canonical_glossary": [
            {
                "term": _clean_text(item.get("term"), max_chars=80),
                "definition": _clean_text(item.get("definition"), max_chars=200),
                "target_chapters": _clean_int_list(item.get("target_chapters"), limit=12),
            }
            for item in _mapping_items(backbone.get("canonical_glossary"), limit=20)
            if _clean_text(item.get("term"))
        ],
        "concept_dependency_graph": [
            {
                "from_concept": _clean_text(item.get("from_concept"), max_chars=80),
                "to_concept": _clean_text(item.get("to_concept"), max_chars=80),
                "relation": _clean_text(item.get("relation"), max_chars=40),
            }
            for item in _mapping_items(backbone.get("concept_dependency_graph"), limit=20)
        ],
        "canonical_claim_pool": [
            {
                "claim_type": _clean_text(item.get("claim_type"), max_chars=40),
                "claim_text": _clean_text(item.get("claim_text"), max_chars=220),
                "target_chapter": _safe_int(item.get("target_chapter"), default=0),
                "source_hint": _clean_text(item.get("source_hint"), max_chars=180),
            }
            for item in _mapping_items(backbone.get("canonical_claim_pool"), limit=60)
            if _clean_text(item.get("claim_text"))
        ],
        "confusion_map": [
            {
                "topic": _clean_text(item.get("topic"), max_chars=80),
                "contrast": _clean_text(item.get("contrast"), max_chars=160),
                "resolution_hint": _clean_text(item.get("resolution_hint"), max_chars=200),
            }
            for item in _mapping_items(backbone.get("confusion_map"), limit=12)
            if _clean_text(item.get("topic"))
        ],
    }


def _learning_taxonomy_snapshot() -> dict[str, Any]:
    return {
        "node_types": [
            {"value": value, "label": label}
            for value, label in _LEARNING_NODE_TYPES.items()
        ],
        "relation_types": [
            {"value": value, "label": label}
            for value, label in _LEARNING_EDGE_TYPES.items()
        ],
    }


def _content_mix_policy_snapshot(*, digest_mode: str, docgen_artifacts: Mapping[str, Any]) -> dict[str, Any]:
    for chapter in _mapping_items(_as_mapping(docgen_artifacts.get("chapter_generation_plan")).get("chapters"), limit=1):
        policy = _as_mapping(_as_mapping(chapter.get("practice_seed_policy")).get("content_mix_policy"))
        density = _as_mapping(_as_mapping(chapter.get("practice_seed_policy")).get("example_density_policy"))
        coverage = _clean_string_list(_as_mapping(chapter.get("practice_seed_policy")).get("coverage_policy"), limit=8)
        if policy or density or coverage:
            return {
                "digest_mode": digest_mode,
                "content_mix_policy": policy,
                "example_density_policy": density,
                "coverage_policy": coverage,
            }
    profile = get_docgen_mode_profile(digest_mode)
    return {
        "digest_mode": profile.mode,
        "content_mix_policy": dict(profile.content_mix_policy),
        "example_density_policy": dict(profile.example_density_policy),
        "coverage_policy": list(profile.coverage_policy),
    }


def _role_coverage_snapshot(chapters: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_index = _safe_int(chapter.get("chapter_index"), default=0)
        targets = _as_mapping(chapter.get("content_role_targets"))
        role_targets = {
            role: _clean_string_list(targets.get(role), limit=12, max_chars=120)
            for role in _LEARNING_NODE_TYPES
        }
        role_targets = {role: values for role, values in role_targets.items() if values}
        if not role_targets:
            continue
        items.append(
            {
                "chapter_index": chapter_index,
                "title": _clean_text(chapter.get("title"), max_chars=160),
                "role_targets": role_targets,
                "role_target_counts": {role: len(values) for role, values in role_targets.items()},
            }
        )
    return items


def _example_coverage_snapshot(chapters: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_index = _safe_int(chapter.get("chapter_index"), default=0)
        plans: list[dict[str, Any]] = []
        for item in _mapping_items(chapter.get("example_coverage_plan"), limit=24):
            target = _clean_text(item.get("target"), max_chars=160)
            if not target:
                continue
            plans.append(
                {
                    "target": target,
                    "example_type": _clean_text(item.get("example_type") or item.get("type"), max_chars=80),
                    "purpose": _clean_text(item.get("purpose"), max_chars=220),
                    "min_examples": _safe_int(item.get("min_examples"), default=1),
                }
            )
        if plans:
            items.append(
                {
                    "chapter_index": chapter_index,
                    "title": _clean_text(chapter.get("title"), max_chars=160),
                    "plans": plans,
                    "planned_example_count": sum(max(1, _safe_int(item.get("min_examples"), default=1)) for item in plans),
                }
            )
    return items


def _intent_profile_v2_snapshot(intent_profile: Mapping[str, Any], *, learning_goal: str) -> dict[str, Any]:
    return {
        "learning_goal_text": _clean_text(intent_profile.get("learning_goal_text") or learning_goal, max_chars=700),
        "audience_profile_text": _clean_text(intent_profile.get("audience_profile_text"), max_chars=700),
        "content_strategy_text": _clean_text(intent_profile.get("content_strategy_text"), max_chars=900),
        "example_practice_policy": _clean_text(intent_profile.get("example_practice_policy"), max_chars=700),
        "source_usage_policy": _clean_text(intent_profile.get("source_usage_policy"), max_chars=700),
        "teaching_intent": _clean_text(intent_profile.get("teaching_intent"), max_chars=500),
        "example_ratio": _safe_float(intent_profile.get("example_ratio"), default=0.0),
        "practice_ratio": _safe_float(intent_profile.get("practice_ratio"), default=0.0),
        "evidence_strictness": _safe_float(intent_profile.get("evidence_strictness"), default=0.0),
        "review_strictness": _safe_float(intent_profile.get("review_strictness"), default=0.0),
        "avoid_list": _clean_string_list(intent_profile.get("avoid_list"), limit=10, max_chars=160),
    }


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _source_file_metadata(
    *,
    file_id: str,
    source_file_lookup: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    metadata = _as_mapping((source_file_lookup or {}).get(file_id))
    result: dict[str, Any] = {
        "file_id": file_id,
    }
    filename = _clean_text(metadata.get("filename"), max_chars=180)
    markdown_path = _clean_text(metadata.get("markdown_path"), max_chars=500)
    markdown_uri = _clean_text(metadata.get("markdown_uri"), max_chars=500)
    if filename:
        result["filename"] = filename
    if markdown_path:
        result["markdown_path"] = markdown_path
    if markdown_uri:
        result["markdown_uri"] = markdown_uri
    return result


def _file_ids_for_ids(
    source_file_ids: Sequence[str],
    *,
    source_file_lookup: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    file_ids: list[str] = []
    seen: set[str] = set()
    for raw_file_id in source_file_ids:
        raw_file_id = str(raw_file_id or "").strip()
        metadata = _as_mapping((source_file_lookup or {}).get(raw_file_id))
        file_id = _clean_text(metadata.get("file_id") or raw_file_id, max_chars=120)
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        file_ids.append(file_id)
    return file_ids


def _file_summary_snapshot(
    docgen_artifacts: Mapping[str, Any],
    *,
    source_file_lookup: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in _mapping_items(docgen_artifacts.get("file_summaries"), limit=12):
        raw_file_id = _clean_text(item.get("file_id"), max_chars=120)
        file_payload = _source_file_metadata(
            file_id=raw_file_id,
            source_file_lookup=source_file_lookup,
        )
        file_payload["filename"] = _clean_text(
            item.get("filename") or file_payload.get("filename"),
            max_chars=180,
        )
        file_payload.update(
            {
                "summary": _clean_text(item.get("summary"), max_chars=_MAX_SUMMARY_TEXT_CHARS),
                "concepts": _clean_string_list(item.get("concepts"), limit=10),
                "question_types": _clean_string_list(item.get("question_types"), limit=8),
                "high_value_sections": _clean_string_list(item.get("high_value_sections"), limit=8, max_chars=180),
                "chapter_slices": _source_slices_snapshot(item.get("chapter_slices"), limit=16),
            }
        )
        summaries.append(file_payload)
    return summaries


def _source_slices_snapshot(value: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    slices: list[dict[str, Any]] = []
    for item in _mapping_items(value, limit=limit):
        section_ref = _clean_text(item.get("section_ref"), max_chars=180)
        if not section_ref:
            continue
        slices.append(
            {
                "chapter_index": _safe_int(item.get("chapter_index"), default=0),
                "file_id": _clean_text(item.get("file_id"), max_chars=120),
                "filename": _clean_text(item.get("filename"), max_chars=180),
                "section_ref": section_ref,
                "section_title": _clean_text(item.get("section_title"), max_chars=180),
                "line_start": _safe_int(item.get("line_start"), default=0),
                "line_end": _safe_int(item.get("line_end"), default=0),
                "summary": _clean_text(item.get("summary"), max_chars=260),
                "reason": _clean_text(item.get("reason"), max_chars=220),
            }
        )
    return slices


def _source_affinity_snapshot(value: Any, *, limit: int = 24) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _mapping_items(value, limit=limit):
        chapter_index = _safe_int(item.get("chapter_index"), default=0)
        if chapter_index <= 0:
            continue
        items.append(
            {
                "chapter_index": chapter_index,
                "file_ids": _clean_string_list(item.get("file_ids"), limit=30, max_chars=120),
                "section_refs": _clean_string_list(item.get("section_refs"), limit=24, max_chars=180),
                "source_slices": _source_slices_snapshot(item.get("source_slices"), limit=12),
            }
        )
    return items


def _confirmed_plan_snapshot(docgen_artifacts: Mapping[str, Any]) -> dict[str, Any]:
    plan = _as_mapping(docgen_artifacts.get("confirmed_plan"))
    if not plan:
        return {}

    chapter_plan: list[dict[str, Any]] = []
    for index, item in enumerate(_mapping_items(plan.get("chapter_plan"), limit=24), start=1):
        chapter_plan.append(
            {
                "chapter_index": _extract_chapter_index(item, index),
                "title": _clean_text(item.get("title") or item.get("name"), max_chars=180),
                "summary": _clean_text(item.get("summary") or item.get("description"), max_chars=500),
                "objective": _clean_text(item.get("objective") or item.get("learning_objective"), max_chars=300),
                "key_points": _clean_string_list(
                    item.get("key_points") or item.get("knowledge_points"),
                    limit=8,
                    max_chars=120,
                ),
            }
        )

    return {
        "plan_summary": _clean_text(plan.get("plan_summary") or plan.get("summary"), max_chars=1200),
        "learning_goal": _clean_text(
            plan.get("learning_goal") or plan.get("goal") or plan.get("user_goal"),
            max_chars=500,
        ),
        "constraints": _clean_string_list(plan.get("constraints") or plan.get("requirements"), limit=10, max_chars=160),
        "selected_file_ids": _clean_string_list(plan.get("selected_file_ids"), limit=100, max_chars=120),
        "chapter_plan": chapter_plan,
    }


def _source_file_ids_for_chapter(
    *,
    chapter: Mapping[str, Any],
    assignment: Mapping[str, Any],
    doc: KnowledgeDoc | None,
) -> list[str]:
    ids = _clean_string_list(chapter.get("source_file_ids"), limit=50, max_chars=120)
    if not ids:
        ids = _clean_string_list(assignment.get("source_file_ids"), limit=50, max_chars=120)
    if not ids and doc is not None:
        ids = _clean_string_list(_load_json_list(doc.source_file_ids), limit=50, max_chars=120)
    return ids


def _build_chapter_snapshots(
    *,
    chapter_metadatas: Sequence[Mapping[str, Any]],
    chapter_assignments: Sequence[Mapping[str, Any]],
    knowledge_docs: Sequence[KnowledgeDoc],
    docgen_artifacts: Mapping[str, Any],
    source_file_lookup: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    plan_by_index = _chapter_plan_lookup(docgen_artifacts)
    docs_by_index = {_safe_int(doc.chapter_index): doc for doc in knowledge_docs}
    chapters: list[dict[str, Any]] = []

    for index, chapter in enumerate(chapter_metadatas, start=1):
        chapter_index = _extract_chapter_index(chapter, index)
        assignment = chapter_assignments[index - 1] if index <= len(chapter_assignments) else {}
        assignment = _as_mapping(assignment)
        doc = docs_by_index.get(chapter_index)
        plan = plan_by_index.get(chapter_index, {})
        title = (
            _clean_text(chapter.get("resolved_title") or chapter.get("title"), max_chars=180)
            or _clean_text(plan.get("enhanced_title") or plan.get("confirmed_title"), max_chars=180)
            or (doc.title if doc is not None else "")
            or f"Chapter {chapter_index}"
        )
        chapter_payload: dict[str, Any] = {
            "chapter_index": chapter_index,
            "doc_id": doc.id if doc is not None else None,
            "title": title,
            "summary": _clean_text(chapter.get("summary") or (doc.summary if doc is not None else ""), max_chars=700),
            "objective": _clean_text(plan.get("objective") or plan.get("chapter_goal"), max_chars=300),
            "source_slices": _source_slices_snapshot(plan.get("source_slices"), limit=12),
        }
        for field_name, limit, max_chars in _CHAPTER_LIST_FIELDS:
            chapter_payload[field_name] = _clean_string_list(plan.get(field_name), limit=limit, max_chars=max_chars)
        role_targets = _as_mapping(plan.get("content_role_targets"))
        chapter_payload["content_role_targets"] = {
            role: _clean_string_list(role_targets.get(role), limit=12, max_chars=120)
            for role in _LEARNING_NODE_TYPES
            if _clean_string_list(role_targets.get(role), limit=12, max_chars=120)
        }
        chapter_payload["example_coverage_plan"] = [
            {
                "target": _clean_text(item.get("target"), max_chars=160),
                "example_type": _clean_text(item.get("example_type") or item.get("type"), max_chars=80),
                "purpose": _clean_text(item.get("purpose"), max_chars=220),
                "min_examples": _safe_int(item.get("min_examples"), default=1),
            }
            for item in _mapping_items(plan.get("example_coverage_plan"), limit=24)
            if _clean_text(item.get("target"))
        ]
        source_file_ids = _source_file_ids_for_chapter(chapter=chapter, assignment=assignment, doc=doc)
        chapter_payload.update(
            {
                "source_file_ids": _file_ids_for_ids(source_file_ids, source_file_lookup=source_file_lookup),
                "digest_mode": _clean_text(
                    chapter.get("digest_mode") or (doc.digest_mode if doc is not None else ""),
                    max_chars=80,
                ),
                "word_count": _safe_int(getattr(doc, "word_count", None) or chapter.get("word_count")),
            }
        )
        chapters.append(chapter_payload)
    return chapters


def _quality_summary_snapshot(docgen_artifacts: Mapping[str, Any]) -> dict[str, Any]:
    review_actions = _mapping_items(docgen_artifacts.get("review_actions"), limit=80)
    repair_trace = _mapping_items(docgen_artifacts.get("repair_trace"), limit=80)
    unresolved = _clean_string_list(docgen_artifacts.get("unresolved_warnings"), limit=20, max_chars=220)
    action_counts: dict[str, int] = {}
    for action in review_actions:
        action_type = _clean_text(action.get("action_type"), max_chars=60) or "unknown"
        action_counts[action_type] = action_counts.get(action_type, 0) + 1
    applied_patch_count = sum(1 for item in repair_trace if _clean_text(item.get("status")) == "applied")
    return {
        "review_decision": _clean_text(docgen_artifacts.get("review_decision"), max_chars=80),
        "review_action_count": len(review_actions),
        "review_action_counts": action_counts,
        "applied_patch_count": applied_patch_count,
        "unresolved_warning_count": len(unresolved),
        "unresolved_warnings": unresolved,
    }


def _kg_candidate_hints_snapshot(
    *,
    chapters: Sequence[Mapping[str, Any]],
    backbone: Mapping[str, Any],
) -> list[dict[str, Any]]:
    terms_by_chapter: dict[int, list[str]] = {}
    for item in _mapping_items(backbone.get("canonical_glossary"), limit=80):
        term = _clean_text(item.get("term"), max_chars=90)
        if not term:
            continue
        for chapter_index in _clean_int_list(item.get("target_chapters"), limit=12):
            terms_by_chapter.setdefault(chapter_index, []).append(term)

    claims_by_chapter: dict[int, list[str]] = {}
    for item in _mapping_items(backbone.get("canonical_claim_pool"), limit=120):
        chapter_index = _safe_int(item.get("target_chapter"), default=0)
        claim_text = _clean_text(item.get("claim_text"), max_chars=180)
        if chapter_index > 0 and claim_text:
            claims_by_chapter.setdefault(chapter_index, []).append(claim_text)

    hints: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_index = _safe_int(chapter.get("chapter_index"), default=0)
        if chapter_index <= 0:
            continue
        concept_candidates = _clean_string_list(
            [
                *list(chapter.get("concept_targets") or []),
                *list(chapter.get("definition_targets") or []),
                *list(chapter.get("formula_targets") or []),
                *terms_by_chapter.get(chapter_index, []),
            ],
            limit=18,
            max_chars=120,
        )
        task_candidates = _clean_string_list(
            [
                *list(chapter.get("example_targets") or []),
                *list(chapter.get("pitfall_targets") or []),
                *claims_by_chapter.get(chapter_index, []),
            ],
            limit=18,
            max_chars=180,
        )
        role_targets = _as_mapping(chapter.get("content_role_targets"))
        candidate_nodes = [
            {
                "node_type": role,
                "label": _LEARNING_NODE_TYPES[role],
                "names": _clean_string_list(role_targets.get(role), limit=10, max_chars=120),
            }
            for role in _LEARNING_NODE_TYPES
            if _clean_string_list(role_targets.get(role), limit=10, max_chars=120)
        ]
        existing_node_types = {str(item.get("node_type") or "") for item in candidate_nodes}
        if concept_candidates and "core_knowledge" not in existing_node_types:
            candidate_nodes.append(
                {
                    "node_type": "core_knowledge",
                    "label": _LEARNING_NODE_TYPES["core_knowledge"],
                    "names": _clean_string_list(concept_candidates, limit=10, max_chars=120),
                }
            )
        if task_candidates and "method_demo" not in existing_node_types:
            candidate_nodes.append(
                {
                    "node_type": "method_demo",
                    "label": _LEARNING_NODE_TYPES["method_demo"],
                    "names": _clean_string_list(task_candidates, limit=8, max_chars=120),
                }
            )
        example_targets = [
            _clean_text(item.get("target"), max_chars=160)
            for item in _mapping_items(chapter.get("example_coverage_plan"), limit=12)
            if _clean_text(item.get("target"))
        ]
        candidate_edges: list[dict[str, Any]] = []
        for target in _clean_string_list([*concept_candidates, *example_targets], limit=10, max_chars=140):
            candidate_edges.append(
                {
                    "source_hint": target,
                    "edge_type": "training",
                    "target_type": "practice_assessment",
                    "reason": "例题、练习或任务应训练并验证该知识点。",
                }
            )
        if not concept_candidates and not task_candidates and not candidate_nodes:
            continue
        hints.append(
            {
                "chapter_index": chapter_index,
                "title": _clean_text(chapter.get("title"), max_chars=160),
                "candidate_terms": concept_candidates,
                "candidate_claims": task_candidates,
                "candidate_nodes": candidate_nodes,
                "candidate_edges": candidate_edges[:12],
                "example_coverage_targets": _clean_string_list(example_targets, limit=12, max_chars=160),
                "source_file_ids": _clean_string_list(chapter.get("source_file_ids"), limit=30, max_chars=120),
                "source_slices": _source_slices_snapshot(chapter.get("source_slices"), limit=8),
                "evidence_policy": "hint_only_require_markdown_or_evidence_ledger_match",
            }
        )
    return hints[:24]


def build_course_learning_context_payload(
    *,
    course_id: str,
    course_name: str | None = None,
    document_context: Mapping[str, Any] | None = None,
    chapter_metadatas: Sequence[Mapping[str, Any]] | None = None,
    chapter_assignments: Sequence[Mapping[str, Any]] | None = None,
    knowledge_docs: Sequence[KnowledgeDoc] | None = None,
    docgen_artifacts: Mapping[str, Any] | None = None,
    course_user_intent: str | None = None,
    course_description: str | None = None,
    source_file_lookup: Mapping[str, Mapping[str, Any]] | None = None,
    version_no: int | None = None,
    build_session_id: str | None = None,
    requested_at: datetime | None = None,
) -> tuple[str, str, dict[str, Any], str]:
    """Build the four course columns from published DocGen outputs."""

    document_context = _as_mapping(document_context)
    docgen_artifacts = _as_mapping(docgen_artifacts)
    docgen_context = _as_mapping(docgen_artifacts.get("docgen_context"))
    intent_profile = _as_mapping(docgen_artifacts.get("intent_profile"))
    build_metadata = _as_mapping(docgen_artifacts.get("build_metadata"))
    chapter_metadatas = _mapping_items(chapter_metadatas)
    chapter_assignments = _mapping_items(chapter_assignments)
    knowledge_docs = list(knowledge_docs or [])
    confirmed_plan = _confirmed_plan_snapshot(docgen_artifacts)
    course_user_intent = _normalize_learning_goal(course_user_intent, max_chars=1200)
    course_description = _clean_text(course_description, max_chars=1200)

    display_name = (
        _clean_text(document_context.get("course_name"))
        or _clean_text(document_context.get("course_display_name"))
        or _clean_text(course_name)
        or "未命名课程"
    )
    digest_mode = _clean_text(document_context.get("digest_mode") or docgen_context.get("digest_mode"))
    plan_summary = _clean_text(
        document_context.get("plan_summary") or docgen_context.get("plan_summary") or confirmed_plan.get("plan_summary"),
        max_chars=1200,
    )
    user_prompt = _clean_text(
        document_context.get("user_prompt") or docgen_context.get("user_prompt"),
        max_chars=1200,
    )
    chapters = _build_chapter_snapshots(
        chapter_metadatas=chapter_metadatas,
        chapter_assignments=chapter_assignments,
        knowledge_docs=knowledge_docs,
        docgen_artifacts=docgen_artifacts,
        source_file_lookup=source_file_lookup,
    )
    file_summaries = _file_summary_snapshot(docgen_artifacts, source_file_lookup=source_file_lookup)
    source_affinity = _source_affinity_snapshot(docgen_artifacts.get("source_affinity_by_chapter"))
    backbone = _document_backbone_snapshot(docgen_artifacts)
    intent_profile_v2 = _intent_profile_v2_snapshot(intent_profile, learning_goal="")
    retrieval_policy = _as_mapping(document_context.get("retrieval_policy") or docgen_artifacts.get("retrieval_policy"))
    course_profile_snapshot = _as_mapping(docgen_artifacts.get("course_profile"))
    material_stats_snapshot = _as_mapping(docgen_artifacts.get("material_stats_profile"))
    quality_summary = _quality_summary_snapshot(docgen_artifacts)

    top_terms = [
        item["term"]
        for item in backbone.get("canonical_glossary", [])
        if isinstance(item, dict) and item.get("term")
    ][:8]
    if not top_terms:
        for summary in file_summaries:
            top_terms.extend(_clean_string_list(summary.get("concepts"), limit=4))
            if len(top_terms) >= 8:
                break
    top_terms = _clean_string_list(top_terms, limit=8, max_chars=80)
    chapter_titles = [chapter["title"] for chapter in chapters if chapter.get("title")]

    learning_goal = _clean_text(
        confirmed_plan.get("learning_goal")
        or intent_profile_v2.get("learning_goal_text")
        or course_user_intent
        or user_prompt,
        max_chars=700,
    )
    intent_profile_v2 = _intent_profile_v2_snapshot(intent_profile, learning_goal=learning_goal)
    intent_lines = []
    if learning_goal:
        intent_lines.append(f"学习目标：{learning_goal}")
    if user_prompt and user_prompt != learning_goal:
        intent_lines.append(f"本次构建请求：{user_prompt}")
    if plan_summary:
        intent_lines.append(f"构建范围：{plan_summary}")
    if chapter_titles:
        intent_lines.append("章节范围：" + "、".join(chapter_titles[:10]))
    if intent_profile_v2.get("audience_profile_text"):
        intent_lines.append(f"学习场景：{intent_profile_v2['audience_profile_text']}")
    if intent_profile_v2.get("content_strategy_text"):
        intent_lines.append(f"讲解策略：{intent_profile_v2['content_strategy_text']}")
    if intent_profile_v2.get("example_practice_policy"):
        intent_lines.append(f"例子与练习：{intent_profile_v2['example_practice_policy']}")
    if intent_profile_v2.get("source_usage_policy"):
        intent_lines.append(f"来源策略：{intent_profile_v2['source_usage_policy']}")
    avoid_list = _clean_string_list(intent_profile.get("avoid_list"), limit=8)
    if avoid_list:
        intent_lines.append("避免：" + "；".join(avoid_list))
    learning_intent_text = _clean_multiline_text("\n".join(intent_lines), max_chars=_MAX_INTENT_TEXT_CHARS)

    intro_bits = []
    if course_description:
        intro_bits.append(f"「{display_name}」：{course_description}")
    else:
        intro_bits.append(f"「{display_name}」当前知识文档以 {digest_mode or 'general'} 模式组织")
    intro_bits.append(f"共 {len(chapters)} 章")
    if top_terms:
        intro_bits.append("重点覆盖 " + "、".join(top_terms[:8]))
    course_intro_text = _clean_text("，".join(intro_bits) + "。", max_chars=_MAX_INTRO_TEXT_CHARS)
    source_file_ids = sorted({file_id for chapter in chapters for file_id in chapter.get("source_file_ids", [])})
    kg_candidate_hints = _kg_candidate_hints_snapshot(chapters=chapters, backbone=backbone)
    learning_taxonomy = _learning_taxonomy_snapshot()
    content_mix_policy = _content_mix_policy_snapshot(digest_mode=digest_mode, docgen_artifacts=docgen_artifacts)
    role_coverage_by_chapter = _role_coverage_snapshot(chapters)
    example_coverage_by_chapter = _example_coverage_snapshot(chapters)

    summary_payload: dict[str, Any] = {
        "schema_version": 3,
        "source": "docgen.publish",
        "generated_at": utcnow().isoformat(),
        "requested_at": requested_at.isoformat() if requested_at is not None else None,
        "course_id": course_id,
        "course_name": display_name,
        "course_description": course_description,
        "course_user_intent": course_user_intent,
        "learning_goal": learning_goal,
        "version_no": _safe_int(version_no or build_metadata.get("version_no")),
        "build_session_id": build_session_id or _clean_text(build_metadata.get("build_session_id")),
        "planner_session_id": _clean_text(build_metadata.get("planner_session_id")),
        "confirmed_plan_id": _clean_text(build_metadata.get("confirmed_plan_id")),
        "digest_mode": digest_mode,
        "retrieval_policy": retrieval_policy,
        "learning_taxonomy": learning_taxonomy,
        "content_mix_policy": content_mix_policy,
        "user_prompt": user_prompt,
        "docgen_user_prompt": user_prompt,
        "plan_summary": plan_summary,
        "chapter_count": len(chapters),
        "chapter_titles": chapter_titles,
        "source_file_ids": _file_ids_for_ids(source_file_ids, source_file_lookup=source_file_lookup),
        "source_files": [
            _source_file_metadata(file_id=file_id, source_file_lookup=source_file_lookup)
            for file_id in source_file_ids
        ],
        "confirmed_plan": confirmed_plan,
        "intent_profile_v2": intent_profile_v2,
        "course_profile": course_profile_snapshot,
        "material_stats_profile": material_stats_snapshot,
        "chapters": chapters,
        "file_summaries": file_summaries,
        "source_affinity_by_chapter": source_affinity,
        "role_coverage_by_chapter": role_coverage_by_chapter,
        "example_coverage_by_chapter": example_coverage_by_chapter,
        "document_backbone": backbone,
        "docgen_learning_backbone": backbone,
        "kg_candidate_hints": kg_candidate_hints,
        "quality_summary": quality_summary,
    }

    llm_context_text = render_course_llm_context(
        course_intro_text=course_intro_text,
        learning_intent_text=learning_intent_text,
        document_summary_json=summary_payload,
    )
    return learning_intent_text, course_intro_text, summary_payload, llm_context_text


def render_course_llm_context(
    *,
    course_intro_text: str,
    learning_intent_text: str,
    document_summary_json: Mapping[str, Any],
) -> str:
    chapters = _as_list(document_summary_json.get("chapters"))
    file_summaries = _as_list(document_summary_json.get("file_summaries"))
    backbone = _as_mapping(document_summary_json.get("document_backbone"))
    intent_profile = _as_mapping(document_summary_json.get("intent_profile_v2"))
    quality_summary = _as_mapping(document_summary_json.get("quality_summary"))
    kg_candidate_hints = _as_list(document_summary_json.get("kg_candidate_hints"))
    content_mix_policy = _as_mapping(document_summary_json.get("content_mix_policy"))
    role_coverage = _as_list(document_summary_json.get("role_coverage_by_chapter"))
    example_coverage = _as_list(document_summary_json.get("example_coverage_by_chapter"))

    lines: list[str] = []
    if course_intro_text:
        lines.extend(["## 课程简介", _clean_text(course_intro_text), ""])
    if learning_intent_text:
        lines.extend(["## 用户学习意图", _clean_multiline_text(learning_intent_text, max_chars=_MAX_INTENT_TEXT_CHARS), ""])

    lines.extend(
        [
            "## 当前知识文档快照",
            f"- 文档版本：v{_safe_int(document_summary_json.get('version_no'))}",
            f"- 构建模式：{_clean_text(document_summary_json.get('digest_mode')) or 'general'}",
            f"- 章节数：{_safe_int(document_summary_json.get('chapter_count'), default=len(chapters))}",
        ]
    )
    plan_summary = _clean_text(document_summary_json.get("plan_summary"), max_chars=900)
    if plan_summary:
        lines.append(f"- 总体方案：{plan_summary}")
    if intent_profile:
        strategy = _clean_text(intent_profile.get("content_strategy_text"), max_chars=500)
        example_policy = _clean_text(intent_profile.get("example_practice_policy"), max_chars=360)
        source_policy = _clean_text(intent_profile.get("source_usage_policy"), max_chars=360)
        if strategy or example_policy or source_policy:
            lines.extend(["", "## 生成意图"])
            if strategy:
                lines.append(f"- 讲解策略：{strategy}")
            if example_policy:
                lines.append(f"- 例子与练习：{example_policy}")
            if source_policy:
                lines.append(f"- 来源策略：{source_policy}")
    if content_mix_policy:
        density = _as_mapping(content_mix_policy.get("example_density_policy"))
        coverage = _clean_string_list(content_mix_policy.get("coverage_policy"), limit=4, max_chars=180)
        lines.extend(["", "## 学习内容分类与例题策略"])
        lines.append("- 节点分类：核心知识、方法示范、解释辅助、原理推理、练习评估、知识组织、应用拓展。")
        lines.append("- 关系分类：前置、包含、推理、应用、说明、训练、对比、相似。")
        if density:
            lines.append(f"- 例题策略：{_clean_text(density.get('policy_text'), max_chars=420)}")
        if coverage:
            lines.append("- 覆盖要求：" + "；".join(coverage))

    if file_summaries:
        lines.extend(["", "## 资料摘要"])
        for item in file_summaries[:8]:
            if not isinstance(item, Mapping):
                continue
            name = _clean_text(item.get("filename"), max_chars=120) or f"file:{item.get('file_id') or ''}"
            summary = _clean_text(item.get("summary"), max_chars=350)
            concepts = "、".join(_clean_string_list(item.get("concepts"), limit=6))
            suffix = f"；核心概念：{concepts}" if concepts else ""
            lines.append(f"- {name}：{summary}{suffix}".rstrip("："))

    if chapters:
        lines.extend(["", "## 章节大纲"])
        for item in chapters[:24]:
            if not isinstance(item, Mapping):
                continue
            title = _clean_text(item.get("title"), max_chars=120) or f"Chapter {item.get('chapter_index') or ''}"
            summary = _clean_text(item.get("summary") or item.get("objective"), max_chars=360)
            points = _clean_string_list(
                item.get("teaching_outline") or item.get("content_points") or item.get("concept_targets"),
                limit=5,
                max_chars=100,
            )
            point_text = f"；重点：{'、'.join(points)}" if points else ""
            lines.append(f"{_safe_int(item.get('chapter_index'))}. {title}：{summary}{point_text}".rstrip("："))

    if example_coverage:
        lines.extend(["", "## 例题覆盖计划"])
        for item in example_coverage[:12]:
            if not isinstance(item, Mapping):
                continue
            title = _clean_text(item.get("title"), max_chars=120)
            plans = _mapping_items(item.get("plans"), limit=5)
            targets = "、".join(_clean_text(plan.get("target"), max_chars=80) for plan in plans if _clean_text(plan.get("target")))
            if targets:
                lines.append(f"- {title}：{targets}")
    if role_coverage:
        lines.extend(["", "## 内容角色覆盖"])
        for item in role_coverage[:8]:
            if not isinstance(item, Mapping):
                continue
            title = _clean_text(item.get("title"), max_chars=120)
            counts = _as_mapping(item.get("role_target_counts"))
            count_text = "、".join(
                f"{_LEARNING_NODE_TYPES.get(role, role)} {_safe_int(count)}"
                for role, count in counts.items()
                if _safe_int(count) > 0
            )
            if count_text:
                lines.append(f"- {title}：{count_text}")

    glossary = [
        item
        for item in _as_list(backbone.get("canonical_glossary"))
        if isinstance(item, Mapping) and _clean_text(item.get("term"))
    ]
    if glossary:
        lines.extend(["", "## 全局术语"])
        for item in glossary[:12]:
            term = _clean_text(item.get("term"), max_chars=80)
            definition = _clean_text(item.get("definition"), max_chars=200)
            lines.append(f"- {term}：{definition}".rstrip("："))

    if kg_candidate_hints:
        lines.extend(["", "## 图谱候选线索"])
        for item in kg_candidate_hints[:10]:
            if not isinstance(item, Mapping):
                continue
            title = _clean_text(item.get("title"), max_chars=120)
            terms = "、".join(_clean_string_list(item.get("candidate_terms"), limit=6, max_chars=80))
            claims = "；".join(_clean_string_list(item.get("candidate_claims"), limit=3, max_chars=120))
            if terms or claims:
                parts = []
                if terms:
                    parts.append(f"候选术语 {terms}")
                if claims:
                    parts.append(f"候选主张 {claims}")
                lines.append(f"- {title}：" + "；".join(parts))

    if quality_summary:
        unresolved_count = _safe_int(quality_summary.get("unresolved_warning_count"), default=0)
        action_count = _safe_int(quality_summary.get("review_action_count"), default=0)
        if action_count or unresolved_count:
            lines.extend(["", "## 质量状态"])
            lines.append(
                f"- review 动作 {action_count} 条，未解决 warning {unresolved_count} 条。"
            )

    return _truncate_text("\n".join(lines), max_chars=_MAX_LLM_CONTEXT_CHARS)


def update_course_learning_context_from_docgen(
    session: Session,
    *,
    course_id: str,
    document_context: Mapping[str, Any] | None,
    chapter_metadatas: Sequence[Mapping[str, Any]],
    chapter_assignments: Sequence[Mapping[str, Any]] | None = None,
    knowledge_docs: Sequence[KnowledgeDoc] | None = None,
    docgen_artifacts: Mapping[str, Any] | None = None,
    version_no: int | None = None,
    build_session_id: str | None = None,
    requested_at: datetime | None = None,
) -> Course | None:
    record = session.exec(select(Course).where(Course.id == course_id)).first()
    if record is None:
        return None

    source_file_lookup = _build_source_file_lookup(
        session,
        course_id=course_id,
        chapter_metadatas=chapter_metadatas,
        chapter_assignments=chapter_assignments,
        knowledge_docs=knowledge_docs,
        docgen_artifacts=docgen_artifacts,
    )

    learning_intent_text, course_intro_text, document_summary_json, llm_context_text = (
        build_course_learning_context_payload(
            course_id=course_id,
            course_name=record.name,
            document_context=document_context,
            chapter_metadatas=chapter_metadatas,
            chapter_assignments=chapter_assignments,
            knowledge_docs=knowledge_docs,
            docgen_artifacts=docgen_artifacts,
            course_user_intent=record.user_intent,
            course_description=record.description,
            source_file_lookup=source_file_lookup,
            version_no=version_no,
            build_session_id=build_session_id,
            requested_at=requested_at,
        )
    )
    record.learning_intent_text = learning_intent_text
    record.course_intro_text = course_intro_text
    record.document_summary_json = document_summary_json
    record.llm_context_text = llm_context_text
    record.updated_at = utcnow()
    session.add(record)
    return record


def _collect_source_file_ids_for_lookup(
    *,
    chapter_metadatas: Sequence[Mapping[str, Any]] | None,
    chapter_assignments: Sequence[Mapping[str, Any]] | None,
    knowledge_docs: Sequence[KnowledgeDoc] | None,
    docgen_artifacts: Mapping[str, Any] | None,
) -> list[str]:
    ids: list[str] = []
    for item in _mapping_items(chapter_metadatas):
        ids.extend(_clean_string_list(item.get("source_file_ids"), limit=100, max_chars=120))
    for item in _mapping_items(chapter_assignments):
        ids.extend(_clean_string_list(item.get("source_file_ids"), limit=100, max_chars=120))
    for doc in list(knowledge_docs or []):
        ids.extend(_clean_string_list(_load_json_list(doc.source_file_ids), limit=100, max_chars=120))
    artifacts = _as_mapping(docgen_artifacts)
    confirmed_plan = _as_mapping(artifacts.get("confirmed_plan"))
    ids.extend(_clean_string_list(confirmed_plan.get("selected_file_ids"), limit=100, max_chars=120))
    for item in _mapping_items(artifacts.get("file_summaries"), limit=100):
        ids.extend(_clean_string_list(item.get("file_id"), limit=1, max_chars=120))
    return sorted(set(ids))


def _build_source_file_lookup(
    session: Session,
    *,
    course_id: str,
    chapter_metadatas: Sequence[Mapping[str, Any]] | None,
    chapter_assignments: Sequence[Mapping[str, Any]] | None,
    knowledge_docs: Sequence[KnowledgeDoc] | None,
    docgen_artifacts: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    source_file_ids = _collect_source_file_ids_for_lookup(
        chapter_metadatas=chapter_metadatas,
        chapter_assignments=chapter_assignments,
        knowledge_docs=knowledge_docs,
        docgen_artifacts=docgen_artifacts,
    )
    if not source_file_ids:
        return {}
    try:
        from app.repositories.files_repo import list_raw_files_by_ids

        raw_files = list_raw_files_by_ids(session, course_id, source_file_ids)
    except Exception:
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for raw_file in raw_files:
        if not raw_file.id:
            continue
        lookup[raw_file.id] = {
            "file_id": raw_file.id,
            "filename": raw_file.filename,
            "markdown_path": raw_file.markdown_path,
            "markdown_uri": raw_file.markdown_uri,
        }
    return lookup


def clear_course_learning_context(session: Session, *, course_id: str) -> bool:
    record = session.exec(select(Course).where(Course.id == course_id)).first()
    if record is None:
        return False
    record.learning_intent_text = ""
    record.course_intro_text = ""
    record.document_summary_json = {}
    record.llm_context_text = ""
    record.updated_at = utcnow()
    session.add(record)
    return True


def load_course_llm_context(session: Session, *, course_id: str, max_chars: int = _MAX_LLM_CONTEXT_CHARS) -> str:
    record = session.exec(select(Course).where(Course.id == course_id)).first()
    if record is None:
        return ""
    return _truncate_text(record.llm_context_text, max_chars=max_chars)


__all__ = [
    "build_course_learning_context_payload",
    "clear_course_learning_context",
    "load_course_llm_context",
    "render_course_llm_context",
    "update_course_learning_context_from_docgen",
]
