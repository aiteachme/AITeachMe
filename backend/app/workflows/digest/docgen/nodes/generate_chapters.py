"""Generate one DocGen chapter from a ChapterGenerationTask."""

from __future__ import annotations

from time import perf_counter
from urllib.parse import urlparse

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt, count_words
from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    upsert_knowledge_build_chapter_preview,
    upsert_knowledge_build_chapter_progress,
)
from app.shared.infra.workflow.live_stream import publish_workflow_stream_event
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.chapter_context import DocGenChapterContextRuntime
from app.workflows.digest.docgen.lib.writer import DocGenWriterRuntime
from app.workflows.digest.docgen.lib.chapter_planning import build_fallback_chapter_markdown
from app.workflows.digest.docgen.lib.chapter_revision import critique_chapter, maybe_rewrite_chapter
from app.workflows.digest.docgen.lib.models import (
    ChapterDraft,
    ChapterGenerationTask,
    ChapterResearchTrace,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    DocumentBackbone,
)
from app.workflows.digest.docgen.lib.quality import (
    align_claim_evidence,
    build_claim_ledger,
    build_evidence_ledger,
    mark_evidence_used,
    resolve_conflicts_for_chapter,
)
from app.workflows.digest.docgen.nodes.common import (
    ensure_chapter_heading,
    extract_markdown_preview_headings,
    publish_docgen_progress,
    resolve_docgen_retrieval_profile,
)
from app.workflows.digest.docgen.state import DocGenState

CHAPTER_LIVE_PREVIEW_MAX_CHARS = 60000
STREAM_DIRECT_MIN_DELTA_CHARS = 48
STREAM_DIRECT_MIN_INTERVAL_S = 0.22
STREAM_PREVIEW_MIN_DELTA_CHARS = 180
STREAM_PREVIEW_MIN_INTERVAL_S = 0.8


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if str(item).strip()))


def _media_hints_from_requests(requests: list[dict]) -> dict[str, list[str]]:
    media_hints = {"mermaid": []}
    for item in requests:
        kind = str(item.get("kind") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        if kind == "mermaid":
            media_hints["mermaid"].append(description)
    return media_hints


def _claim_targets_for_writer(claim_ledger: ClaimLedger | None) -> list[str]:
    return [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text]


def _evidence_bindings_for_writer(claim_evidence_map: ClaimEvidenceMap | None) -> list[dict]:
    return [
        binding.model_dump(mode="json")
        for binding in list((claim_evidence_map or ClaimEvidenceMap()).bindings or [])
    ]


def _conflict_warnings_for_writer(conflict_report: ConflictReport | None) -> list[str]:
    return [
        item.detail
        for item in list((conflict_report or ConflictReport()).items or [])
        if item.severity in {"warning", "error"} and item.detail
    ]


def _execution_contract_for_writer(
    task: ChapterGenerationTask,
    *,
    required_elements: list[str],
    media_hints: dict[str, list[str]],
    claim_ledger: ClaimLedger | None,
    claim_evidence_map: ClaimEvidenceMap | None,
    conflict_report: ConflictReport | None,
) -> dict:
    practice_style = str((task.practice_seed_policy or {}).get("style") or "").strip().lower()
    worked_example_target = 3 if practice_style == "exam" else 1
    return {
        "target_word_count": task.target_word_count,
        "min_word_count": task.min_word_count,
        "coverage_requirements": required_elements,
        "min_coverage_score": task.coverage_threshold,
        "min_evidence_support": task.evidence_support_threshold,
        "claim_targets": _claim_targets_for_writer(claim_ledger),
        "evidence_bindings": _evidence_bindings_for_writer(claim_evidence_map),
        "conflict_warnings": _conflict_warnings_for_writer(conflict_report),
        "repair_enabled": True,
        "practice_quota": {
            "worked_examples": worked_example_target,
            "short_answer": 0,
            "self_check": 0,
            "reasoning": 1 if practice_style != "exam" else 0,
            "application": 1 if practice_style != "exam" else 0,
        },
        "media_quota": {
            "mermaid": len(media_hints["mermaid"]),
        },
    }


def _chapter_plan_for_writer(
    task: ChapterGenerationTask,
    *,
    total_chapters: int,
    claim_ledger: ClaimLedger | None = None,
    claim_evidence_map: ClaimEvidenceMap | None = None,
    conflict_report: ConflictReport | None = None,
) -> dict:
    # Writer plan 是给写作器看的合同快照；结构化证据不在这里静默截断。
    media_hints = _media_hints_from_requests(task.placeholder_requests)
    required_elements = _unique_strings(
        [
            *task.content_points,
            *task.concept_targets,
            *task.definition_targets,
            *task.formula_targets,
            *task.example_targets,
            *task.pitfall_targets,
        ]
    )
    return {
        "chapter_index": task.chapter_index,
        "total_chapters": total_chapters,
        "title": task.confirmed_title,
        "resolved_title": task.enhanced_title,
        "objective": task.objective,
        "required_elements": required_elements,
        "search_queries": task.retrieval_queries,
        "writing_instructions": "\n".join([*task.teaching_outline, *task.writing_rules]),
        "media_hints": media_hints,
        "execution_contract": _execution_contract_for_writer(
            task,
            required_elements=required_elements,
            media_hints=media_hints,
            claim_ledger=claim_ledger,
            claim_evidence_map=claim_evidence_map,
            conflict_report=conflict_report,
        ),
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


def _source_preview_metadata(source_details: list[dict]) -> dict[str, list[str]]:
    domains: list[str] = []
    source_titles: list[str] = []
    source_urls: list[str] = []
    seen_domains: set[str] = set()
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()

    for item in source_details:
        raw_url = str(item.get("url") or "").strip()
        raw_title = str(item.get("title") or item.get("source_title") or "").strip()
        if raw_url and not raw_url.startswith("local://"):
            domain = urlparse(raw_url).netloc.strip().lower()
            if domain and domain not in seen_domains and len(domains) < 4:
                domains.append(domain)
                seen_domains.add(domain)
            if raw_url not in seen_urls and len(source_urls) < 4:
                source_urls.append(raw_url)
                seen_urls.add(raw_url)
        if raw_title and raw_title not in seen_titles and len(source_titles) < 4:
            source_titles.append(raw_title)
            seen_titles.add(raw_title)

    return {
        "domains": domains,
        "source_titles": source_titles,
        "source_urls": source_urls,
    }


def _trim_preview_markdown(markdown: str, *, max_chars: int = 1200) -> str:
    text = markdown.strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\n\n..."


def _chapter_live_preview_markdown(markdown: str, *, title: str) -> str:
    text = str(markdown or "").strip()
    if not text:
        return f"# {title}\n\n正在接收写作流..."
    if not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    return _trim_preview_markdown(text, max_chars=CHAPTER_LIVE_PREVIEW_MAX_CHARS)


def _append_preview_list(lines: list[str], title: str, values: list[str], *, limit: int = 6) -> None:
    items = _unique_strings([str(item).strip() for item in values])[:limit]
    if not items:
        return
    lines.extend(["", f"## {title}", ""])
    lines.extend(f"- {item}" for item in items)


def _task_preview_markdown(
    task: ChapterGenerationTask,
    *,
    title: str,
    total_chapters: int,
) -> str:
    lines = [
        f"# {title}",
        "",
        "正在启动本章生成。先展示本章执行合同，检索完成后会刷新证据来源，正文生成完成后会替换为初稿片段。",
        "",
        "## 生成目标",
        "",
        task.objective or "系统正在根据章节 brief 整理本章目标。",
    ]
    if total_chapters > 0:
        lines.extend(
            [
                "",
                "## 执行范围",
                "",
                f"- 章节位置：第 {task.chapter_index} / {total_chapters} 章",
                f"- 目标字数：约 {task.target_word_count} 字",
            ]
        )
    _append_preview_list(
        lines,
        "即将覆盖的重点",
        [
            *task.content_points,
            *task.concept_targets,
            *task.definition_targets,
            *task.formula_targets,
            *task.example_targets,
            *task.pitfall_targets,
        ],
    )
    _append_preview_list(lines, "检索线索", task.retrieval_queries, limit=5)
    _append_preview_list(lines, "写作路径", task.teaching_outline, limit=5)
    return _trim_preview_markdown("\n".join(lines), max_chars=1200)


def _research_preview_markdown(
    *,
    title: str,
    dense_context: str,
    source_details: list[dict],
    research_trace: ChapterResearchTrace,
    local_hit_count: int,
    web_hit_count: int,
    fallback_used: bool,
) -> str:
    read_url_count = int(research_trace.budget_used.get("read_url_count", 0) or 0)
    document_count = int(research_trace.budget_used.get("document_count", 0) or 0)
    source_titles = [
        str(item.get("title") or item.get("source_title") or item.get("url") or "").strip()
        for item in source_details
    ]
    lines = [
        f"# {title}",
        "",
        "检索与证据整理已完成，正在进入正文写作。这里先展示本章已经锁定的资料范围和证据线索。",
        "",
        "## 检索结果",
        "",
        f"- 本地命中：{local_hit_count}",
        f"- 联网命中：{web_hit_count}",
        f"- 已执行查询：{len(research_trace.executed_queries)}",
        f"- 已打开网页：{read_url_count}",
        f"- 已纳入文档：{document_count}",
    ]
    if fallback_used:
        lines.append("- 检索出现异常，系统会使用章节 brief 兜底生成。")
    _append_preview_list(lines, "执行过的查询", research_trace.executed_queries, limit=5)
    _append_preview_list(lines, "已纳入证据来源", source_titles, limit=5)
    _append_preview_list(lines, "仍需补强的点", research_trace.gap_notes, limit=4)
    if dense_context.strip():
        lines.extend(["", "## 上下文摘录", "", build_draft_excerpt(dense_context, max_chars=420)])
    return _trim_preview_markdown("\n".join(lines), max_chars=1400)


def build_generate_chapters_node(*, context: WorkflowContext):
    """构建单章生成节点。

    该节点通过 LangGraph Send 按章 fan-out 运行。每次调用只处理一个
    ChapterGenerationTask：检索和读取资料、构造 evidence/claim/conflict
    账本、调用 writer 生成草稿，并把单章产物通过 reducer fan-in 回主图。
    """

    async def generate_chapters_node(state: DocGenState) -> dict:
        """生成一个章节的草稿和研究账本。"""

        started_at = perf_counter()
        task = ChapterGenerationTask.model_validate(state["chapter_task"])
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        total_chapters = int(state.get("total_chapters", 0) or 0)
        title = task.enhanced_title or task.confirmed_title
        task_preview = _task_preview_markdown(task, title=title, total_chapters=total_chapters)

        stream_preview_last_text = ""

        def _publish_preview_delta(preview_markdown: str, *, status: str) -> None:
            nonlocal stream_preview_last_text
            text = str(preview_markdown or "").strip()
            if not text or text == stream_preview_last_text:
                return
            previous = stream_preview_last_text
            mode = "append" if previous and text.startswith(previous) else "replace"
            stream_preview_last_text = text
            publish_workflow_stream_event(
                state["subject"],
                "preview_delta",
                {
                    "kind": "chapter_preview",
                    "chapter_index": task.chapter_index,
                    "title": title,
                    "status": status,
                    "mode": mode,
                    "base_length": len(previous),
                    "text": text[len(previous):] if mode == "append" else text,
                    "full_length": len(text),
                    "updated_at": utcnow().isoformat(),
                },
            )

        _publish_preview_delta(task_preview, status="generating")
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={"chapter_index": task.chapter_index, "title": title, "status": "generating"},
        )
        upsert_knowledge_build_chapter_preview(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_preview={
                "chapter_index": task.chapter_index,
                "title": title,
                "status": "generating",
                "excerpt": task_preview,
                "latest_headings": extract_markdown_preview_headings(task_preview),
                "word_count": 0,
                "source_count": 0,
            },
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
            retrieval_profile=str(
                state.get("retrieval_profile")
                or resolve_docgen_retrieval_profile(
                    state.get("digest_mode"),
                    user_prompt=state.get("user_prompt"),
                    subject_name=state.get("subject"),
                )
            ),
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
        research_preview = _research_preview_markdown(
            title=title,
            dense_context=dense_context,
            source_details=source_details,
            research_trace=research_trace,
            local_hit_count=local_hit_count,
            web_hit_count=web_hit_count,
            fallback_used=fallback_used,
        )
        _publish_preview_delta(research_preview, status="generating")
        upsert_knowledge_build_chapter_preview(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_preview={
                "chapter_index": task.chapter_index,
                "title": title,
                "status": "generating",
                "excerpt": research_preview,
                "latest_headings": extract_markdown_preview_headings(research_preview),
                "word_count": 0,
                "source_count": len(source_details),
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "chapter_research_ready",
                "chapter_index": task.chapter_index,
                "title": title,
                "summary": (
                    f"{title} 检索已完成：本地命中 {local_hit_count}，联网命中 {web_hit_count}，"
                    f"纳入 {len(source_details)} 个来源，开始正文写作。"
                ),
                "created_at": utcnow(),
                **_source_preview_metadata(source_details),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_research_ready",
            payload={
                "chapter_index": task.chapter_index,
                "title": title,
                "local_hits": local_hit_count,
                "web_hits": web_hit_count,
                "source_count": len(source_details),
                "query_count": len(research_trace.executed_queries),
                "fallback_used": fallback_used,
            },
        )

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
        stream_direct_last_at = 0.0
        stream_direct_last_len = 0
        stream_preview_last_at = 0.0
        stream_preview_last_len = 0
        stream_progress_marked = False

        async def _publish_writer_stream_preview(accumulated_markdown: str) -> None:
            nonlocal stream_direct_last_at, stream_direct_last_len
            nonlocal stream_preview_last_at, stream_preview_last_len, stream_progress_marked
            raw_markdown = str(accumulated_markdown or "").strip()
            if not raw_markdown:
                return
            now = perf_counter()
            current_len = len(raw_markdown)
            preview_markdown = _chapter_live_preview_markdown(raw_markdown, title=title)
            if (
                current_len - stream_direct_last_len >= STREAM_DIRECT_MIN_DELTA_CHARS
                or now - stream_direct_last_at >= STREAM_DIRECT_MIN_INTERVAL_S
            ):
                stream_direct_last_at = now
                stream_direct_last_len = current_len
                _publish_preview_delta(preview_markdown, status="drafting")
            if (
                current_len - stream_preview_last_len < STREAM_PREVIEW_MIN_DELTA_CHARS
                and now - stream_preview_last_at < STREAM_PREVIEW_MIN_INTERVAL_S
            ):
                return
            stream_preview_last_at = now
            stream_preview_last_len = current_len
            if not stream_progress_marked:
                stream_progress_marked = True
                upsert_knowledge_build_chapter_progress(
                    state["subject"],
                    requested_at=state["requested_at"],
                    chapter_progress={
                        "chapter_index": task.chapter_index,
                        "title": title,
                        "status": "drafting",
                        "source_count": len(source_details),
                        "local_hits": local_hit_count,
                        "web_hits": web_hit_count,
                        "query_count": len(research_trace.executed_queries),
                    },
                )
            upsert_knowledge_build_chapter_preview(
                state["subject"],
                requested_at=state["requested_at"],
                chapter_preview={
                    "chapter_index": task.chapter_index,
                    "title": title,
                    "status": "drafting",
                    "excerpt": preview_markdown,
                    "latest_headings": extract_markdown_preview_headings(preview_markdown),
                    "word_count": count_words(raw_markdown),
                    "source_count": len(source_details),
                },
            )

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
                digest_mode=state.get("digest_mode") or "systematic",
                on_stream_update=_publish_writer_stream_preview,
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
        word_count = count_words(writer_markdown)
        final_preview = _chapter_live_preview_markdown(writer_markdown, title=title)
        _publish_preview_delta(final_preview, status="generated")
        upsert_knowledge_build_chapter_preview(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_preview={
                "chapter_index": task.chapter_index,
                "title": title,
                "status": "generated",
                "excerpt": final_preview,
                "latest_headings": extract_markdown_preview_headings(writer_markdown),
                "word_count": word_count,
                "source_count": len(source_details),
            },
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
                "word_count": word_count,
                "fallback_used": fallback_used,
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "chapter_generated",
                "chapter_index": task.chapter_index,
                "title": title,
                "summary": f"{title} 初稿已完成，约 {word_count} 字，引用 {len(source_details)} 个来源。",
                "created_at": utcnow(),
                **_source_preview_metadata(source_details),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_generated",
            payload={
                "chapter_index": task.chapter_index,
                "title": title,
                "word_count": word_count,
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
