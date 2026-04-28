"""Subject-level learning context snapshot helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.models.knowledge_doc import KnowledgeDoc
from app.models.subject import Subject
from app.utils.time import utcnow

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
        "canonical_glossary": [
            {
                "term": _clean_text(item.get("term"), max_chars=80),
                "definition": _clean_text(item.get("definition"), max_chars=200),
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


def _source_file_metadata(
    *,
    raw_file_id: int,
    source_file_lookup: Mapping[int, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    metadata = _as_mapping((source_file_lookup or {}).get(raw_file_id))
    result: dict[str, Any] = {
        "file_id": raw_file_id,
        "raw_file_id": raw_file_id,
    }
    file_uid = _clean_text(metadata.get("uid") or metadata.get("file_uid"), max_chars=120)
    filename = _clean_text(metadata.get("filename"), max_chars=180)
    markdown_path = _clean_text(metadata.get("markdown_path"), max_chars=500)
    markdown_uri = _clean_text(metadata.get("markdown_uri"), max_chars=500)
    if file_uid:
        result["file_uid"] = file_uid
    if filename:
        result["filename"] = filename
    if markdown_path:
        result["markdown_path"] = markdown_path
    if markdown_uri:
        result["markdown_uri"] = markdown_uri
    return result


def _file_uids_for_ids(
    source_file_ids: Sequence[int],
    *,
    source_file_lookup: Mapping[int, Mapping[str, Any]] | None,
) -> list[str]:
    uids: list[str] = []
    seen: set[str] = set()
    for raw_file_id in source_file_ids:
        metadata = _as_mapping((source_file_lookup or {}).get(int(raw_file_id)))
        uid = _clean_text(metadata.get("uid") or metadata.get("file_uid"), max_chars=120)
        if not uid or uid in seen:
            continue
        seen.add(uid)
        uids.append(uid)
    return uids


def _file_summary_snapshot(
    docgen_artifacts: Mapping[str, Any],
    *,
    source_file_lookup: Mapping[int, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in _mapping_items(docgen_artifacts.get("file_summaries"), limit=12):
        raw_file_id = _safe_int(item.get("file_id"))
        file_payload = _source_file_metadata(
            raw_file_id=raw_file_id,
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
                "file_id": _safe_int(item.get("file_id"), default=0),
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
        "selected_file_ids": _clean_int_list(plan.get("selected_file_ids"), limit=100),
        "chapter_plan": chapter_plan,
    }


def _source_file_ids_for_chapter(
    *,
    chapter: Mapping[str, Any],
    assignment: Mapping[str, Any],
    doc: KnowledgeDoc | None,
) -> list[int]:
    ids = _clean_int_list(chapter.get("source_file_ids"), limit=50)
    if not ids:
        ids = _clean_int_list(assignment.get("source_file_ids"), limit=50)
    if not ids and doc is not None:
        ids = _clean_int_list(_load_json_list(doc.source_file_ids), limit=50)
    return ids


def _build_chapter_snapshots(
    *,
    chapter_metadatas: Sequence[Mapping[str, Any]],
    chapter_assignments: Sequence[Mapping[str, Any]],
    knowledge_docs: Sequence[KnowledgeDoc],
    docgen_artifacts: Mapping[str, Any],
    source_file_lookup: Mapping[int, Mapping[str, Any]] | None = None,
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
        source_file_ids = _source_file_ids_for_chapter(chapter=chapter, assignment=assignment, doc=doc)
        chapter_payload.update(
            {
                "source_file_ids": source_file_ids,
                "source_raw_file_ids": source_file_ids,
                "source_file_uids": _file_uids_for_ids(source_file_ids, source_file_lookup=source_file_lookup),
                "digest_mode": _clean_text(
                    chapter.get("digest_mode") or (doc.digest_mode if doc is not None else ""),
                    max_chars=80,
                ),
                "word_count": _safe_int(getattr(doc, "word_count", None) or chapter.get("word_count")),
            }
        )
        chapters.append(chapter_payload)
    return chapters


def build_subject_learning_context_payload(
    *,
    subject_id: str,
    subject_name: str | None = None,
    document_context: Mapping[str, Any] | None = None,
    chapter_metadatas: Sequence[Mapping[str, Any]] | None = None,
    chapter_assignments: Sequence[Mapping[str, Any]] | None = None,
    knowledge_docs: Sequence[KnowledgeDoc] | None = None,
    docgen_artifacts: Mapping[str, Any] | None = None,
    subject_user_intent: str | None = None,
    subject_description: str | None = None,
    source_file_lookup: Mapping[int, Mapping[str, Any]] | None = None,
    version_no: int | None = None,
    build_session_id: str | None = None,
    requested_at: datetime | None = None,
) -> tuple[str, str, dict[str, Any], str]:
    """Build the four subject columns from published DocGen outputs."""

    document_context = _as_mapping(document_context)
    docgen_artifacts = _as_mapping(docgen_artifacts)
    docgen_context = _as_mapping(docgen_artifacts.get("docgen_context"))
    intent_profile = _as_mapping(docgen_artifacts.get("intent_profile"))
    build_metadata = _as_mapping(docgen_artifacts.get("build_metadata"))
    chapter_metadatas = _mapping_items(chapter_metadatas)
    chapter_assignments = _mapping_items(chapter_assignments)
    knowledge_docs = list(knowledge_docs or [])
    confirmed_plan = _confirmed_plan_snapshot(docgen_artifacts)
    subject_user_intent = _normalize_learning_goal(subject_user_intent, max_chars=1200)
    subject_description = _clean_text(subject_description, max_chars=1200)

    display_name = (
        _clean_text(document_context.get("subject_name"))
        or _clean_text(document_context.get("subject_display_name"))
        or _clean_text(subject_name)
        or "未命名学科"
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
    backbone = _document_backbone_snapshot(docgen_artifacts)

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
        confirmed_plan.get("learning_goal") or subject_user_intent or user_prompt,
        max_chars=700,
    )
    intent_lines = []
    if learning_goal:
        intent_lines.append(f"学习目标：{learning_goal}")
    if user_prompt and user_prompt != learning_goal:
        intent_lines.append(f"本次构建请求：{user_prompt}")
    if plan_summary:
        intent_lines.append(f"构建范围：{plan_summary}")
    if chapter_titles:
        intent_lines.append("章节范围：" + "、".join(chapter_titles[:10]))
    style_bits = _clean_string_list(
        [
            f"文档风格 {_clean_text(intent_profile.get('document_style'))}" if intent_profile.get("document_style") else "",
            f"讲解深度 {_clean_text(intent_profile.get('explanation_depth'))}" if intent_profile.get("explanation_depth") else "",
            f"定义深度 {_clean_text(intent_profile.get('definition_depth'))}" if intent_profile.get("definition_depth") else "",
            f"例题偏好 {_clean_text(intent_profile.get('example_preference'))}" if intent_profile.get("example_preference") else "",
        ],
        limit=6,
        max_chars=80,
    )
    if style_bits:
        intent_lines.append("讲义偏好：" + "；".join(style_bits))
    avoid_list = _clean_string_list(intent_profile.get("avoid_list"), limit=8)
    if avoid_list:
        intent_lines.append("避免：" + "；".join(avoid_list))
    learning_intent_text = _clean_multiline_text("\n".join(intent_lines), max_chars=_MAX_INTENT_TEXT_CHARS)

    intro_bits = []
    if subject_description:
        intro_bits.append(f"「{display_name}」：{subject_description}")
    else:
        intro_bits.append(f"「{display_name}」当前知识文档以 {digest_mode or 'general'} 模式组织")
    intro_bits.append(f"共 {len(chapters)} 章")
    if top_terms:
        intro_bits.append("重点覆盖 " + "、".join(top_terms[:8]))
    subject_intro_text = _clean_text("，".join(intro_bits) + "。", max_chars=_MAX_INTRO_TEXT_CHARS)
    source_file_ids = sorted({file_id for chapter in chapters for file_id in chapter.get("source_file_ids", [])})

    summary_payload: dict[str, Any] = {
        "schema_version": 1,
        "source": "docgen.publish",
        "generated_at": utcnow().isoformat(),
        "requested_at": requested_at.isoformat() if requested_at is not None else None,
        "subject": subject,
        "subject_name": display_name,
        "subject_description": subject_description,
        "subject_user_intent": subject_user_intent,
        "learning_goal": learning_goal,
        "version_no": _safe_int(version_no or build_metadata.get("version_no")),
        "build_session_id": build_session_id or _clean_text(build_metadata.get("build_session_id")),
        "planner_session_id": _clean_text(build_metadata.get("planner_session_id")),
        "confirmed_plan_id": _clean_text(build_metadata.get("confirmed_plan_id")),
        "digest_mode": digest_mode,
        "user_prompt": user_prompt,
        "docgen_user_prompt": user_prompt,
        "plan_summary": plan_summary,
        "chapter_count": len(chapters),
        "chapter_titles": chapter_titles,
        "source_file_ids": source_file_ids,
        "source_raw_file_ids": source_file_ids,
        "source_file_uids": _file_uids_for_ids(source_file_ids, source_file_lookup=source_file_lookup),
        "source_files": [
            _source_file_metadata(raw_file_id=file_id, source_file_lookup=source_file_lookup)
            for file_id in source_file_ids
        ],
        "confirmed_plan": confirmed_plan,
        "chapters": chapters,
        "file_summaries": file_summaries,
        "document_backbone": backbone,
    }

    llm_context_text = render_subject_llm_context(
        subject_intro_text=subject_intro_text,
        learning_intent_text=learning_intent_text,
        document_summary_json=summary_payload,
    )
    return learning_intent_text, subject_intro_text, summary_payload, llm_context_text


def render_subject_llm_context(
    *,
    subject_intro_text: str,
    learning_intent_text: str,
    document_summary_json: Mapping[str, Any],
) -> str:
    chapters = _as_list(document_summary_json.get("chapters"))
    file_summaries = _as_list(document_summary_json.get("file_summaries"))
    backbone = _as_mapping(document_summary_json.get("document_backbone"))

    lines: list[str] = []
    if subject_intro_text:
        lines.extend(["## 学科简介", _clean_text(subject_intro_text), ""])
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

    return _truncate_text("\n".join(lines), max_chars=_MAX_LLM_CONTEXT_CHARS)


def update_subject_learning_context_from_docgen(
    session: Session,
    *,
    subject_id: str,
    document_context: Mapping[str, Any] | None,
    chapter_metadatas: Sequence[Mapping[str, Any]],
    chapter_assignments: Sequence[Mapping[str, Any]] | None = None,
    knowledge_docs: Sequence[KnowledgeDoc] | None = None,
    docgen_artifacts: Mapping[str, Any] | None = None,
    version_no: int | None = None,
    build_session_id: str | None = None,
    requested_at: datetime | None = None,
) -> Subject | None:
    record = session.exec(select(Subject).where(Subject.id == subject_id)).first()
    if record is None:
        return None

    source_file_lookup = _build_source_file_lookup(
        session,
        subject_id=subject_id,
        chapter_metadatas=chapter_metadatas,
        chapter_assignments=chapter_assignments,
        knowledge_docs=knowledge_docs,
        docgen_artifacts=docgen_artifacts,
    )

    learning_intent_text, subject_intro_text, document_summary_json, llm_context_text = (
        build_subject_learning_context_payload(
            subject_id=subject_id,
            subject_name=record.name,
            document_context=document_context,
            chapter_metadatas=chapter_metadatas,
            chapter_assignments=chapter_assignments,
            knowledge_docs=knowledge_docs,
            docgen_artifacts=docgen_artifacts,
            subject_user_intent=record.user_intent,
            subject_description=record.description,
            source_file_lookup=source_file_lookup,
            version_no=version_no,
            build_session_id=build_session_id,
            requested_at=requested_at,
        )
    )
    record.learning_intent_text = learning_intent_text
    record.subject_intro_text = subject_intro_text
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
) -> list[int]:
    ids: list[int] = []
    for item in _mapping_items(chapter_metadatas):
        ids.extend(_clean_int_list(item.get("source_file_ids"), limit=100))
    for item in _mapping_items(chapter_assignments):
        ids.extend(_clean_int_list(item.get("source_file_ids"), limit=100))
    for doc in list(knowledge_docs or []):
        ids.extend(_clean_int_list(_load_json_list(doc.source_file_ids), limit=100))
    artifacts = _as_mapping(docgen_artifacts)
    confirmed_plan = _as_mapping(artifacts.get("confirmed_plan"))
    ids.extend(_clean_int_list(confirmed_plan.get("selected_file_ids"), limit=100))
    for item in _mapping_items(artifacts.get("file_summaries"), limit=100):
        ids.extend(_clean_int_list(item.get("file_id"), limit=1))
    return sorted(set(ids))


def _build_source_file_lookup(
    session: Session,
    *,
    subject_id: str,
    chapter_metadatas: Sequence[Mapping[str, Any]] | None,
    chapter_assignments: Sequence[Mapping[str, Any]] | None,
    knowledge_docs: Sequence[KnowledgeDoc] | None,
    docgen_artifacts: Mapping[str, Any] | None,
) -> dict[int, dict[str, Any]]:
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

        raw_files = list_raw_files_by_ids(session, subject_id, source_file_ids)
    except Exception:
        return {}
    lookup: dict[int, dict[str, Any]] = {}
    for raw_file in raw_files:
        if raw_file.id is None:
            continue
        lookup[int(raw_file.id)] = {
            "uid": raw_file.uid,
            "filename": raw_file.filename,
            "markdown_path": raw_file.markdown_path,
            "markdown_uri": raw_file.markdown_uri,
        }
    return lookup


def clear_subject_learning_context(session: Session, *, subject_id: str) -> bool:
    record = session.exec(select(Subject).where(Subject.id == subject_id)).first()
    if record is None:
        return False
    record.learning_intent_text = ""
    record.subject_intro_text = ""
    record.document_summary_json = {}
    record.llm_context_text = ""
    record.updated_at = utcnow()
    session.add(record)
    return True


def load_subject_llm_context(session: Session, *, subject_id: str, max_chars: int = _MAX_LLM_CONTEXT_CHARS) -> str:
    record = session.exec(select(Subject).where(Subject.id == subject_id)).first()
    if record is None:
        return ""
    return _truncate_text(record.llm_context_text, max_chars=max_chars)


__all__ = [
    "build_subject_learning_context_payload",
    "clear_subject_learning_context",
    "load_subject_llm_context",
    "render_subject_llm_context",
    "update_subject_learning_context_from_docgen",
]
