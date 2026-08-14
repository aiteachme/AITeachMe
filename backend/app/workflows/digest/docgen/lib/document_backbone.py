"""Document-level knowledge backbone for DocGen."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import structlog
from pydantic_core import from_json

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.llm_support.structured import (
    parse_structured_response_text,
    repair_json_string_escapes,
)
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs_with_metadata,
)
from app.workflows.digest.docgen.lib.models import (
    BackboneConflictWarning,
    BackboneResearchAgenda,
    CanonicalClaim,
    ChapterExecutionBrief,
    ChapterGenerationPlan,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocumentPreparationBundle,
    DocumentBackbone,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    clean_string_list,
)
from app.workflows.digest.docgen.prompts.document_backbone import build_document_backbone_messages


logger = structlog.get_logger(__name__)

DocumentPreparationProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
_STREAM_PREVIEW_MIN_CHARS = 240
_BACKBONE_STREAM_SECTIONS = (
    ("canonical_glossary", "concept_dependency_graph"),
    ("concept_dependency_graph", "notation_registry"),
    ("notation_registry", "canonical_claim_pool"),
    ("canonical_claim_pool", "confusion_map"),
    ("confusion_map", "source_trust_summary"),
)


def _preview_text(value: object, *, limit: int = 96) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)].rstrip()}…"


def _preview_string_list(value: object, *, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _preview_text(item, limit=item_limit)
        if text:
            items.append(text)
    return items


def _backbone_section_items(section: str, raw_items: object) -> list[str]:
    if not isinstance(raw_items, list):
        return []
    items: list[str] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        if section == "canonical_glossary":
            text = _preview_text(raw_item.get("term"))
        elif section == "concept_dependency_graph":
            source = _preview_text(raw_item.get("from_concept"), limit=44)
            target = _preview_text(raw_item.get("to_concept"), limit=44)
            text = f"{source} → {target}" if source and target else source or target
        elif section == "notation_registry":
            symbol = _preview_text(raw_item.get("symbol"), limit=28)
            meaning = _preview_text(raw_item.get("meaning"), limit=60)
            text = f"{symbol}：{meaning}" if symbol and meaning else symbol or meaning
        elif section == "canonical_claim_pool":
            text = _preview_text(raw_item.get("claim_text"))
        else:
            topic = _preview_text(raw_item.get("topic"), limit=48)
            contrast = _preview_text(raw_item.get("contrast"), limit=72)
            text = f"{topic}：{contrast}" if topic and contrast else topic or contrast
        if text:
            items.append(text)
    return items


async def _publish_stream_previews(
    payload: object,
    *,
    callback: DocumentPreparationProgressCallback,
    published_sections: set[str],
    published_briefs: set[int],
    final: bool,
) -> None:
    if not isinstance(payload, Mapping):
        return

    backbone = payload.get("document_backbone")
    if isinstance(backbone, Mapping):
        for section, following_section in _BACKBONE_STREAM_SECTIONS:
            if section in published_sections:
                continue
            if not final and following_section not in backbone:
                continue
            raw_items = backbone.get(section)
            items = _backbone_section_items(section, raw_items)
            await callback(
                "backbone_section",
                {
                    "section": section,
                    "item_count": len(raw_items) if isinstance(raw_items, list) else 0,
                    "items": items,
                },
            )
            published_sections.add(section)

    raw_briefs = payload.get("chapter_execution_briefs")
    if not isinstance(raw_briefs, list):
        return
    for position, raw_brief in enumerate(raw_briefs):
        if not isinstance(raw_brief, Mapping):
            continue
        chapter_index = int(raw_brief.get("chapter_index", 0) or 0)
        if chapter_index <= 0 or chapter_index in published_briefs:
            continue
        brief_is_complete = final or position < len(raw_briefs) - 1 or "fallback_used" in raw_brief
        if not brief_is_complete:
            continue
        await callback(
            "chapter_execution_brief",
            {
                "chapter_index": chapter_index,
                "teaching_outline": _preview_string_list(
                    raw_brief.get("teaching_outline"), item_limit=100
                ),
                "writing_instructions": _preview_string_list(
                    raw_brief.get("writing_instructions"), item_limit=120
                ),
                "retrieval_queries": _preview_string_list(
                    raw_brief.get("retrieval_queries"), item_limit=100
                ),
            },
        )
        published_briefs.add(chapter_index)


async def _stream_document_preparation_bundle(
    *,
    messages: list[dict[str, str]],
    completion_kwargs: dict[str, object],
    callback: DocumentPreparationProgressCallback,
) -> DocumentPreparationBundle:
    chunks: list[str] = []
    total_chars = 0
    buffered_chars = 0
    published_sections: set[str] = set()
    published_briefs: set[int] = set()

    async for chunk in acompletion_stream(
        messages,
        **completion_kwargs,
    ):
        chunks.append(chunk)
        total_chars += len(chunk)
        if total_chars - buffered_chars < _STREAM_PREVIEW_MIN_CHARS:
            continue
        buffered_chars = total_chars
        raw_buffer = "".join(chunks)
        partial_source = repair_json_string_escapes(raw_buffer) or raw_buffer
        try:
            partial_payload = from_json(partial_source, allow_partial=True)
        except ValueError:
            continue
        await _publish_stream_previews(
            partial_payload,
            callback=callback,
            published_sections=published_sections,
            published_briefs=published_briefs,
            final=False,
        )

    raw_text = "".join(chunks).strip()
    bundle = parse_structured_response_text(DocumentPreparationBundle, raw_text)
    payload = bundle.model_dump(mode="json")
    await _publish_stream_previews(
        payload,
        callback=callback,
        published_sections=published_sections,
        published_briefs=published_briefs,
        final=True,
    )
    return bundle


def build_document_backbone(
    *,
    task_seeds: Sequence[ChapterGenerationTaskSeed],
    agenda: BackboneResearchAgenda,
    evidence_units: Sequence[HighConfidenceEvidenceUnit],
    file_summaries: Sequence[FileMaterialSummary],
) -> tuple[DocumentBackbone, list[BackboneConflictWarning]]:
    """Compile evidence metadata without inventing semantic graph structure.

    Required elements are Planner-authored coverage targets, not necessarily
    glossary terms, factual claims or prerequisite concepts.  Semantic units and
    relations are extracted from the completed chapters by the KG LLM lane.
    """

    del agenda
    warnings: list[BackboneConflictWarning] = []
    source_types = Counter(unit.source_type for unit in evidence_units)
    evidence_confidence = [unit.confidence for unit in evidence_units]
    source_trust_summary = {
        "evidence_unit_count": len(evidence_units),
        "source_type_counts": dict(source_types),
        "avg_evidence_confidence": round(sum(evidence_confidence) / len(evidence_confidence), 4) if evidence_confidence else 0.0,
        "file_summary_count": len(file_summaries),
    }
    if not evidence_units:
        warnings.append(
            BackboneConflictWarning(
                warning_id="bb_no_evidence_units",
                severity="warning",
                detail="未找到高置信证据候选，文档骨架将主要依赖 confirmed plan 和文件摘要。",
            )
        )
    return (
        DocumentBackbone(
            source_trust_summary=source_trust_summary,
            fallback_used=False,
        ),
        warnings,
    )


async def generate_document_backbone(
    *,
    course_name: str,
    digest_mode: str,
    task_seeds: Sequence[ChapterGenerationTaskSeed],
    agenda: BackboneResearchAgenda,
    evidence_units: Sequence[HighConfidenceEvidenceUnit],
    file_summaries: Sequence[FileMaterialSummary],
    learner_profile_text: str = "",
    extra_metadata: dict[str, object] | None = None,
    max_retrieval_queries_per_chapter: int = 2,
    progress_callback: DocumentPreparationProgressCallback | None = None,
) -> tuple[DocumentBackbone, list[ChapterExecutionBrief], list[BackboneConflictWarning]]:
    """Generate one whole-document backbone and every chapter execution brief."""

    retrieval_query_limit = max(1, min(8, int(max_retrieval_queries_per_chapter)))

    metadata_backbone, warnings = build_document_backbone(
        task_seeds=task_seeds,
        agenda=agenda,
        evidence_units=evidence_units,
        file_summaries=file_summaries,
    )

    messages = build_document_backbone_messages(
        course_name=course_name,
        digest_mode=digest_mode,
        task_seeds=[item.model_dump(mode="json") for item in task_seeds],
        research_agenda=agenda.model_dump(mode="json"),
        evidence_units=[item.model_dump(mode="json") for item in evidence_units],
        file_summaries=[item.model_dump(mode="json") for item in file_summaries],
        learner_profile_text=learner_profile_text,
        max_retrieval_queries_per_chapter=retrieval_query_limit,
    )
    completion_kwargs = docgen_completion_kwargs_with_metadata(
        DocGenModelStep.DOCUMENT_BACKBONE,
        digest_mode=digest_mode,
        extra_metadata=extra_metadata,
        docgen_stage="build_document_backbone",
        chapter_count=len(task_seeds),
        file_summary_count=len(file_summaries),
        evidence_unit_count=len(evidence_units),
    )

    try:
        if progress_callback is not None:
            try:
                bundle = await _stream_document_preparation_bundle(
                    messages=messages,
                    completion_kwargs=completion_kwargs,
                    callback=progress_callback,
                )
            except Exception as stream_exc:
                logger.warning(
                    "document_backbone_stream_failed_using_structured_call",
                    error=str(stream_exc),
                )
                await progress_callback(
                    "stream_repair",
                    {"reason": "stream_output_not_validated"},
                )
                response = await acompletion_with_fallback(
                    messages,
                    **completion_kwargs,
                    response_model=DocumentPreparationBundle,
                )
                bundle = (
                    response
                    if isinstance(response, DocumentPreparationBundle)
                    else DocumentPreparationBundle.model_validate(response)
                )
        else:
            response = await acompletion_with_fallback(
                messages,
                **completion_kwargs,
                response_model=DocumentPreparationBundle,
            )
            bundle = (
                response
                if isinstance(response, DocumentPreparationBundle)
                else DocumentPreparationBundle.model_validate(response)
            )
        backbone = bundle.document_backbone
        expected_brief_indices = [int(seed.chapter_index) for seed in task_seeds]
        returned_brief_indices = [int(item.chapter_index) for item in bundle.chapter_execution_briefs]
        briefs_by_index = {
            int(item.chapter_index): item
            for item in bundle.chapter_execution_briefs
        }
        missing_brief_indices = [
            chapter_index
            for chapter_index in expected_brief_indices
            if chapter_index not in briefs_by_index
        ]
        if (
            len(returned_brief_indices) != len(expected_brief_indices)
            or len(briefs_by_index) != len(returned_brief_indices)
            or set(returned_brief_indices) != set(expected_brief_indices)
        ):
            raise ValueError(
                "document preparation returned invalid chapter brief indices: "
                f"expected={expected_brief_indices}, returned={returned_brief_indices}, "
                f"missing={missing_brief_indices}"
            )
        normalized_briefs = []
        seed_by_index = {int(seed.chapter_index): seed for seed in task_seeds}
        for chapter_index in expected_brief_indices:
            brief = briefs_by_index[chapter_index]
            seed = seed_by_index[chapter_index]
            retrieval_queries = clean_string_list(
                brief.retrieval_queries or seed.retrieval_queries,
                limit=retrieval_query_limit,
            )
            normalized_briefs.append(
                brief.model_copy(update={"retrieval_queries": retrieval_queries})
            )
        return (
            backbone.model_copy(
                update={
                    "source_trust_summary": metadata_backbone.source_trust_summary,
                    "fallback_used": False,
                }
            ),
            normalized_briefs,
            warnings,
        )
    except Exception as exc:
        logger.warning(
            "docgen_document_backbone_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        warnings.append(
            BackboneConflictWarning(
                warning_id="bb_llm_fallback",
                severity="warning",
                detail="整本文档语义骨架生成失败，本轮降级为空语义骨架；章节仍按确认方案继续生成。",
            )
        )
        fallback_briefs = [
            ChapterExecutionBrief(
                chapter_index=seed.chapter_index,
                retrieval_queries=clean_string_list(
                    seed.retrieval_queries,
                    limit=retrieval_query_limit,
                ),
                writing_instructions=list(seed.style_rules),
                fallback_used=True,
            )
            for seed in task_seeds
        ]
        return metadata_backbone.model_copy(update={"fallback_used": True}), fallback_briefs, warnings


def apply_backbone_to_chapter_plan(
    *,
    plan: ChapterGenerationPlan,
    backbone: DocumentBackbone,
) -> ChapterGenerationPlan:
    claims_by_chapter: dict[int, list[CanonicalClaim]] = defaultdict(list)
    for claim in backbone.canonical_claim_pool:
        if claim.target_chapter is not None:
            claims_by_chapter[int(claim.target_chapter)].append(claim)
    glossary_by_chapter: dict[int, list[str]] = defaultdict(list)
    for item in backbone.canonical_glossary:
        for chapter_index in item.target_chapters:
            glossary_by_chapter[int(chapter_index)].append(item.term)
    confusion_by_chapter: dict[int, list[str]] = defaultdict(list)
    for item in backbone.confusion_map:
        for chapter_index in item.target_chapters:
            confusion_by_chapter[int(chapter_index)].append(item.topic or item.contrast)

    updated_tasks: list[ChapterGenerationTask] = []
    for task in plan.chapters:
        claim_targets = clean_string_list(
            [
                *task.claim_targets,
                *[claim.claim_text for claim in claims_by_chapter.get(task.chapter_index, [])],
            ],
            limit=18,
        )
        concept_targets = clean_string_list(
            [
                *task.concept_targets,
                *glossary_by_chapter.get(task.chapter_index, []),
            ],
            limit=18,
        )
        dependency_refs = clean_string_list(
            [
                edge.from_concept
                for edge in backbone.concept_dependency_graph
                if edge.to_concept in concept_targets or edge.to_concept in task.required_elements
            ],
            limit=12,
        )
        forward_refs = clean_string_list(
            [
                edge.to_concept
                for edge in backbone.concept_dependency_graph
                if edge.from_concept in concept_targets or edge.from_concept in task.required_elements
            ],
            limit=12,
        )
        updated_tasks.append(
            task.model_copy(
                update={
                    "claim_targets": claim_targets,
                    "concept_targets": concept_targets,
                    "confusion_targets": clean_string_list(
                        [*task.confusion_targets, *confusion_by_chapter.get(task.chapter_index, [])],
                        limit=16,
                    ),
                    "dependency_refs": dependency_refs,
                    "forward_refs": forward_refs,
                    "coverage_threshold": task.coverage_threshold or 0.62,
                    "evidence_support_threshold": task.evidence_support_threshold or 0.5,
                    "repetition_tolerance": task.repetition_tolerance or 0.35,
                    "patch_tolerance": task.patch_tolerance or 0.35,
                }
            )
        )
    return plan.model_copy(update={"chapters": updated_tasks})


__all__ = [
    "apply_backbone_to_chapter_plan",
    "build_document_backbone",
    "generate_document_backbone",
]
