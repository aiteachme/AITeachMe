"""Generate one DocGen chapter from a ChapterGenerationTask."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt, count_words
from app.utils.docgen_store import append_knowledge_build_recent_event, upsert_knowledge_build_chapter_progress
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib import DocGenChapterContextRuntime, DocGenWriterRuntime
from app.workflows.digest.docgen.lib.chapter_critic import critique_chapter, maybe_rewrite_chapter
from app.workflows.digest.docgen.lib.chapter_generation import build_fallback_chapter_markdown
from app.workflows.digest.docgen.lib.claims import align_claim_evidence, build_claim_ledger
from app.workflows.digest.docgen.lib.conflicts import resolve_conflicts_for_chapter
from app.workflows.digest.docgen.lib.evidence import build_evidence_ledger, mark_evidence_used
from app.workflows.digest.docgen.lib.models import (
    ChapterDraft,
    ChapterGenerationTask,
    ChapterResearchTrace,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    DocumentBackbone,
)
from app.workflows.digest.docgen.nodes.common import (
    ensure_chapter_heading,
    publish_docgen_progress,
    resolve_docgen_course_type,
    resolve_docgen_retrieval_profile,
)
from app.workflows.digest.docgen.state import DocGenState


def _chapter_plan_for_writer(
    task: ChapterGenerationTask,
    *,
    total_chapters: int,
    claim_ledger: ClaimLedger | None = None,
    claim_evidence_map: ClaimEvidenceMap | None = None,
    conflict_report: ConflictReport | None = None,
) -> dict:
    media_hints = {"mermaid": [], "images": []}
    for item in task.placeholder_requests:
        kind = str(item.get("kind") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        if kind == "mermaid":
            media_hints["mermaid"].append(description)
        elif kind in {"image", "images"}:
            media_hints["images"].append(description)
    required = [
        *task.content_points,
        *task.concept_targets,
        *task.definition_targets,
        *task.formula_targets,
        *task.example_targets,
        *task.pitfall_targets,
    ]
    return {
        "chapter_index": task.chapter_index,
        "total_chapters": total_chapters,
        "title": task.confirmed_title,
        "resolved_title": task.enhanced_title,
        "objective": task.objective,
        "required_elements": list(dict.fromkeys(required))[:16],
        "search_queries": task.retrieval_queries,
        "writing_instructions": "\n".join([*task.teaching_outline, *task.writing_rules]),
        "media_hints": media_hints,
        "execution_contract": {
            "target_word_count": task.target_word_count,
            "min_word_count": task.min_word_count,
            "coverage_requirements": list(dict.fromkeys(required))[:16],
            "min_coverage_score": task.coverage_threshold,
            "min_evidence_support": task.evidence_support_threshold,
            "claim_targets": [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or [])[:10]],
            "evidence_bindings": [
                binding.model_dump(mode="json")
                for binding in list((claim_evidence_map or ClaimEvidenceMap()).bindings or [])[:10]
            ],
            "conflict_warnings": [
                item.detail
                for item in list((conflict_report or ConflictReport()).items or [])
                if item.severity in {"warning", "error"}
            ][:8],
            "repair_enabled": True,
            "media_quota": {
                "mermaid": len(media_hints["mermaid"]),
                "images": len(media_hints["images"]),
            },
        },
        "source_file_ids": task.priority_file_ids,
        "placeholder_requests": task.placeholder_requests,
    }


def _source_scope(source_details: list[dict]) -> dict:
    local = [item for item in source_details if str(item.get("url") or "").startswith("local://")]
    web = [item for item in source_details if str(item.get("url") or "") and not str(item.get("url") or "").startswith("local://")]
    return {
        "source_count": len(source_details),
        "local_source_count": len(local),
        "web_source_count": len(web),
    }


def build_generate_chapters_node(*, context: WorkflowContext):
    async def generate_chapters_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        task = ChapterGenerationTask.model_validate(state["chapter_task"])
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        total_chapters = int(state.get("total_chapters", 0) or 0)
        title = task.enhanced_title or task.confirmed_title
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={"chapter_index": task.chapter_index, "title": title, "status": "generating"},
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "chapter_generating",
                "chapter_index": task.chapter_index,
                "title": title,
                "summary": f"{title} 开始执行章节生成：检索、证据整理、写作和审校。",
                "created_at": utcnow(),
            },
        )
        traced_context = TracedExecutionContext(
            subject=state["subject"],
            build_session_id=state.get("build_session_id", ""),
            workflow_context=context,
            planner_session_id=state.get("planner_session_id", ""),
            confirmed_plan_id=state.get("confirmed_plan_id", ""),
            digest_mode=state.get("digest_mode", ""),
            course_type=resolve_docgen_course_type(state.get("course_type") or state.get("digest_mode")),
            retrieval_profile=str(state.get("retrieval_profile") or resolve_docgen_retrieval_profile(state.get("digest_mode"))),
            teaching_action="chapter_generate",
            chapter_index=task.chapter_index,
        )
        dense_context = ""
        sources: list[str] = []
        source_details: list[dict] = []
        research_trace = ChapterResearchTrace(chapter_index=task.chapter_index)
        local_hit_count = 0
        web_hit_count = 0
        research_started_at = perf_counter()
        fallback_used = False
        try:
            shared_inputs = state.get("shared_inputs")
            runtime = DocGenChapterContextRuntime(traced_context)
            research = await runtime.run(
                queries=task.retrieval_queries[: max(1, task.budget_policy.max_local_queries + task.budget_policy.max_web_queries)],
                local_rag_subject=state["subject"],
                local_sections=list(getattr(shared_inputs, "section_packets", []) or []),
                chapter_title=title,
                objective=task.objective,
                required_elements=task.content_points or task.concept_targets,
                digest_mode=state.get("digest_mode") or "",
                retrieval_profile=traced_context.retrieval_profile,
                selected_skillpacks=list(state.get("selected_skillpacks") or []),
                user_goal=str((state.get("docgen_context") or {}).get("user_goal") or ""),
                max_research_rounds=task.budget_policy.max_research_rounds,
                max_context_chars=task.budget_policy.max_context_chars,
                query_cap=max(1, task.budget_policy.max_local_queries + task.budget_policy.max_web_queries),
                queries_per_round=max(1, task.budget_policy.max_local_queries),
                max_gap_queries_per_round=max(1, task.budget_policy.max_web_queries),
            )
            dense_context = research.content.strip()
            sources = list(research.sources)
            source_details = list(research.metadata.get("source_details", []) or [])
            local_hit_count = int(research.metadata.get("local_hits", 0) or 0)
            web_hit_count = int(research.metadata.get("web_hits", 0) or 0)
            research_trace = ChapterResearchTrace(
                chapter_index=task.chapter_index,
                rounds=list(research.metadata.get("research_rounds", []) or []),
                executed_queries=list(research.metadata.get("executed_queries", []) or []),
                opened_contexts=source_details[: task.budget_policy.max_opened_urls],
                stop_reason=str(research.metadata.get("stop_reason") or ""),
                budget_used={
                    "query_count": int(research.metadata.get("query_count", 0) or 0),
                    "local_hits": local_hit_count,
                    "web_hits": web_hit_count,
                    "read_url_count": int(research.metadata.get("read_url_count", 0) or 0),
                    "document_count": int(research.metadata.get("document_count", 0) or 0),
                },
                coverage_score=float(research.metadata.get("coverage_score", 0.0) or 0.0),
                gap_notes=list(research.metadata.get("gaps_remaining", []) or []),
            )
        except Exception as exc:
            fallback_used = True
            research_trace.stop_reason = f"research_failed:{str(exc)[:160]}"
        research_ms = int((perf_counter() - research_started_at) * 1000)

        targets = [
            *task.content_points,
            *task.concept_targets,
            *task.definition_targets,
            *task.formula_targets,
            *task.example_targets,
            *task.pitfall_targets,
        ]
        evidence_ledger = build_evidence_ledger(
            chapter_index=task.chapter_index,
            dense_context=dense_context,
            source_details=source_details,
            targets=targets,
        )
        try:
            claim_ledger = build_claim_ledger(
                task=task,
                evidence_ledger=evidence_ledger,
                document_backbone=document_backbone,
            )
            claim_ledger, claim_evidence_map = align_claim_evidence(
                claim_ledger=claim_ledger,
                evidence_ledger=evidence_ledger,
            )
        except Exception:
            claim_ledger = ClaimLedger(
                chapter_index=task.chapter_index,
                fallback_used=True,
            )
            claim_evidence_map = ClaimEvidenceMap(
                chapter_index=task.chapter_index,
                fallback_used=True,
            )
        try:
            conflict_report = resolve_conflicts_for_chapter(
                task=task,
                evidence_ledger=evidence_ledger,
                document_backbone=document_backbone,
            )
        except Exception:
            conflict_report = ConflictReport(
                chapter_index=task.chapter_index,
                fallback_used=True,
            )
        writer_markdown = ""
        try:
            writer = DocGenWriterRuntime(traced_context)
            writer_result = await writer.run(
                chapter_plan=_chapter_plan_for_writer(
                    task,
                    total_chapters=total_chapters,
                    claim_ledger=claim_ledger,
                    claim_evidence_map=claim_evidence_map,
                    conflict_report=conflict_report,
                ),
                dense_context=dense_context,
                tone=state.get("tone") or "encouraging",
                digest_mode=state.get("digest_mode") or "systematic",
                selected_skillpacks=list(state.get("selected_skillpacks") or []),
                user_goal=str((state.get("docgen_context") or {}).get("user_goal") or ""),
            )
            writer_markdown = ensure_chapter_heading(title, writer_result.content)
        except Exception as exc:
            fallback_used = True
            writer_markdown = build_fallback_chapter_markdown(
                task=task,
                digest_mode=state.get("digest_mode") or "systematic",
                reason=f"writer_failed:{str(exc)[:120]}",
            )
        quality = critique_chapter(
            markdown=writer_markdown,
            required_points=targets,
            digest_mode=state.get("digest_mode") or "systematic",
            source_count=len(source_details),
            min_word_count=task.min_word_count,
        )
        try:
            writer = DocGenWriterRuntime(traced_context)
            writer_markdown, quality = await maybe_rewrite_chapter(
                llm=writer.context.resolve_llm_caller(),
                markdown=writer_markdown,
                title=title,
                digest_mode=state.get("digest_mode") or "systematic",
                required_points=targets,
                dense_context=dense_context,
                quality=quality,
                max_retries=task.budget_policy.max_writer_retries,
                extra_metadata=traced_context.trace_metadata(chapter_index=task.chapter_index),
            )
        except Exception:
            pass
        evidence_ledger = mark_evidence_used(evidence_ledger, writer_markdown)
        claim_ledger, claim_evidence_map = align_claim_evidence(
            claim_ledger=claim_ledger,
            evidence_ledger=evidence_ledger,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        source_scope = _source_scope(source_details)
        source_scope.update(
            {
                "local_hits": local_hit_count,
                "web_hits": web_hit_count,
                "query_count": len(research_trace.executed_queries),
                "read_url_count": int(research_trace.budget_used.get("read_url_count", 0) or 0),
                "document_count": int(research_trace.budget_used.get("document_count", 0) or 0),
            }
        )
        draft = ChapterDraft(
            chapter_index=task.chapter_index,
            title=title,
            markdown=writer_markdown,
            summary_draft=build_draft_excerpt(writer_markdown, max_chars=260),
            research_trace=research_trace,
            evidence_ledger=evidence_ledger,
            claim_ledger_ref=f"ch{task.chapter_index:02d}_claim_ledger",
            conflict_warning_refs=[item.conflict_id for item in conflict_report.items if item.severity in {"warning", "error"}],
            source_scope=source_scope,
            quality_signals=quality,
            placeholder_requests=task.placeholder_requests,
            sources=sources,
            source_details=source_details,
            fallback_used=fallback_used,
        )
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={
                "chapter_index": task.chapter_index,
                "title": title,
                "status": "generated",
                "source_count": len(source_details),
                "local_hits": local_hit_count,
                "web_hits": web_hit_count,
                "query_count": len(research_trace.executed_queries),
                "word_count": count_words(writer_markdown),
                "fallback_used": fallback_used,
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_generated",
            payload={
                "chapter_index": task.chapter_index,
                "title": title,
                "word_count": count_words(writer_markdown),
                "quality_score": quality.quality_score,
                "fallback_used": fallback_used,
            },
        )
        return {
            "chapter_drafts": [draft.model_dump(mode="json")],
            "research_traces": [research_trace.model_dump(mode="json")],
            "evidence_ledgers": [evidence_ledger.model_dump(mode="json")],
            "claim_ledgers": [claim_ledger.model_dump(mode="json")],
            "claim_evidence_maps": [claim_evidence_map.model_dump(mode="json")],
            "conflict_reports": [conflict_report.model_dump(mode="json")],
            "research_sources": sources,
            "research_ms": research_ms,
            "draft_ms": elapsed_ms,
            "llm_calls_total": 2 + (1 if quality.rewrite_used else 0),
        }

    return generate_chapters_node


__all__ = ["build_generate_chapters_node"]
