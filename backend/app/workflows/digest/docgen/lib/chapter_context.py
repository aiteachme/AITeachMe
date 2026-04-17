"""Workflow-local chapter context runtime for digest DocGen."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from langsmith import traceable

from app.shared.infra.settings import get_settings
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.search import ContextCompressor, SourceCurator
from app.shared.infra.search.factory import get_configured_retriever_names, get_retrievers_for_subject
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.skills import collect_recommended_tool_tags, render_prompt_scoped_skillpacks
from app.shared.infra.tools.builtin.web_reading import read_urls
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.docgen.lib.query_planning import (
    build_research_focus_text,
    dedupe_queries,
    enrich_queries_for_education,
    generate_sub_queries,
)
from app.workflows.digest.docgen.prompts import build_docgen_research_purify_messages

_LOW_VALUE_SOURCE_MARKERS = (
    "baidu.com/zhidao",
    "360doc.com",
    "docin.com",
)
_TERM_SPLIT_RE = re.compile(r"[，。；：、,.!?\n\r/（）()\-]+")
_MODE_RESEARCH_STRATEGIES = {
    "sprint": {
        "max_rounds": 2,
        "queries_per_round": 2,
        "query_cap": 4,
        "coverage_target": 0.68,
        "max_total_chars": 4200,
        "min_score_gain": 0.08,
        "max_gap_queries_per_round": 2,
    },
    "systematic": {
        "max_rounds": 3,
        "queries_per_round": 3,
        "query_cap": 6,
        "coverage_target": 0.82,
        "max_total_chars": 6000,
        "min_score_gain": 0.05,
        "max_gap_queries_per_round": 3,
    },
}


class DocGenChapterContextRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "DocGen"

    @property
    def trace_name(self) -> str:
        return "章节研究上下文"

    async def execute(
        self,
        *,
        queries: list[str],
        local_rag_subject: str | None = None,
        local_sections: list[Any] | None = None,
        chapter_title: str = "",
        objective: str = "",
        required_elements: list[str] | None = None,
        digest_mode: str = "",
        retrieval_profile: str | None = None,
        selected_skillpacks: list[str] | None = None,
        user_goal: str = "",
        search_domain: str = "zh",
        max_results_per_query: int | None = None,
        max_research_rounds: int | None = None,
        max_context_chars: int | None = None,
        query_cap: int | None = None,
        queries_per_round: int | None = None,
        max_gap_queries_per_round: int | None = None,
    ) -> TracedExecutionResult:
        settings = get_settings()
        query_limit = max_results_per_query or settings.search.max_results_per_query
        strategy = self._resolve_strategy(digest_mode)
        if max_research_rounds is not None:
            strategy["max_rounds"] = max(1, int(max_research_rounds))
        if max_context_chars is not None:
            strategy["max_total_chars"] = max(1000, int(max_context_chars))
        if queries_per_round is not None:
            strategy["queries_per_round"] = max(1, int(queries_per_round))
        if max_gap_queries_per_round is not None:
            strategy["max_gap_queries_per_round"] = max(1, int(max_gap_queries_per_round))
        resolved_query_cap = max(
            max(1, int(settings.docgen.max_research_queries)),
            int(strategy["query_cap"]),
        )
        if query_cap is not None:
            resolved_query_cap = max(1, int(query_cap))
        base_queries = dedupe_queries(queries, limit=resolved_query_cap)
        if not base_queries and str(chapter_title).strip():
            base_queries = [str(chapter_title).strip()]
        if not base_queries:
            return TracedExecutionResult(metadata={"local_hits": 0, "web_hits": 0, "query_count": 0})

        focus_text = build_research_focus_text(
            title=chapter_title or base_queries[0],
            objective=objective,
            required_elements=required_elements,
            digest_mode=digest_mode,
        )
        skillpack_guidance = render_prompt_scoped_skillpacks(
            selected_skillpacks,
            prompt_scope="digest.docgen.research",
            bindings={
                "subject": self.context.subject,
                "user_goal": user_goal,
                "chapter_title": chapter_title or base_queries[0],
                "topic": chapter_title or base_queries[0],
                "concept": chapter_title or base_queries[0],
            },
        )
        recommended_tool_tags = collect_recommended_tool_tags(
            selected_skillpacks,
            prompt_scope="digest.docgen.research",
        )
        planned_queries = await generate_sub_queries(
            focus_text or base_queries[0],
            context=[
                *base_queries,
                {"title": chapter_title, "objective": objective},
                *[
                    {"name": item}
                    for item in list(required_elements or [])
                    if str(item).strip()
                ],
            ],
            max_queries=resolved_query_cap,
            domain=search_domain,
            llm_caller=self.context.resolve_llm_caller(),
            extra_metadata=self.context.trace_metadata(
                runtime_name=self.name,
                research_stage="plan_sub_queries",
            ),
            skillpack_guidance=skillpack_guidance,
            recommended_tool_tags=recommended_tool_tags,
        )
        pending_queries = dedupe_queries([*base_queries, *planned_queries], limit=resolved_query_cap)
        resolved_retrieval_profile = str(retrieval_profile or self.context.retrieval_profile or "").strip()
        external_search_enabled = get_teaching_runtime_config().planner.allow_external_search
        local_retriever = LocalRAGRetriever(subject=local_rag_subject, local_sections=local_sections)
        other_retrievers = [
            retriever
            for retriever in get_retrievers_for_subject(
                subject=local_rag_subject,
                local_sections=local_sections,
                profile=resolved_retrieval_profile or None,
                include_external=external_search_enabled,
            )
            if retriever.name != local_retriever.name
        ]
        configured_retrievers = get_configured_retriever_names(
            profile=resolved_retrieval_profile or None,
            include_local_rag=bool(local_rag_subject or local_sections),
            include_external=external_search_enabled,
            include_fallback=True,
        )
        compressor = ContextCompressor(self.context)
        curator = SourceCurator(self.context)

        all_results: list[SearchResult] = []
        local_hits = 0
        web_hits = 0
        fallback_queries: list[str] = []
        executed_queries: list[str] = []
        retriever_stats: dict[str, dict[str, Any]] = {}
        research_rounds: list[dict[str, Any]] = []
        coverage_score = 0.0
        gaps_remaining: list[str] = []
        stop_reason = "round_cap"
        curated_results: list[SearchResult] = []
        curator_metadata: dict[str, Any] = {}
        documents: list[str] = []
        dense_context = ""
        compression_mode = "empty"
        read_url_count = 0
        page_cache: dict[str, ScrapedPage] = {}
        previous_score = 0.0
        previous_curated_count = 0
        retrieval_started_at = time.monotonic()
        retrieval_budget_s = max(1.0, float(settings.docgen.retrieval_timeout_s))
        provider_budget_s = max(0.5, float(settings.search.provider_timeout_s))

        for round_index in range(1, int(strategy["max_rounds"]) + 1):
            if time.monotonic() - retrieval_started_at >= retrieval_budget_s:
                stop_reason = "retrieval_budget_exhausted"
                break

            round_queries = self._take_round_queries(
                pending_queries,
                executed_queries=executed_queries,
                limit=int(strategy["queries_per_round"]),
            )
            if not round_queries:
                stop_reason = "query_queue_exhausted"
                break

            round_result = await self._run_research_round(
                round_index=round_index,
                round_queries=round_queries,
                search_domain=search_domain,
                query_limit=query_limit,
                settings=settings,
                local_retriever=local_retriever,
                other_retrievers=other_retrievers,
                local_hits_total=local_hits,
                web_hits_total=web_hits,
                fallback_queries_total=fallback_queries,
                executed_queries=executed_queries,
                retriever_stats=retriever_stats,
                all_results=all_results,
                retrieval_started_at=retrieval_started_at,
                retrieval_budget_s=retrieval_budget_s,
                provider_budget_s=provider_budget_s,
            )
            local_hits = int(round_result["local_hits_total"])
            web_hits = int(round_result["web_hits_total"])
            round_local_hits = int(round_result["round_local_hits"])
            round_web_hits = int(round_result["round_web_hits"])
            round_fallback_queries = list(round_result["round_fallback_queries"])
            round_external_queries = list(round_result.get("round_external_queries", []) or [])

            merged_results = self._dedupe_results(
                self._filter_search_results(all_results),
                max_results=max(query_limit * max(1, len(executed_queries)), query_limit),
            )
            curated_results, curator_metadata = await curator.curate_sources(
                query=focus_text or base_queries[0],
                sources=merged_results,
                max_results=max(query_limit * 2, len(executed_queries) * 2),
            )
            documents, read_url_count = await self._collect_documents(
                curated_results,
                page_cache=page_cache,
                read_timeout_s=float(settings.docgen.read_timeout_s),
            )
            if not documents:
                documents = [item.to_text() for item in curated_results if item.to_text().strip()]

            compression_result = await compressor.run(
                query=focus_text or base_queries[0],
                focus_terms=list(required_elements or []),
                documents=documents,
                max_results=8,
                max_total_chars=int(strategy["max_total_chars"]),
            )
            dense_context = compression_result.content.strip()
            compression_mode = compression_result.metadata.get("compression_mode", "empty")
            assessment = self._assess_coverage(
                dense_context=dense_context,
                objective=objective,
                required_elements=list(required_elements or []),
                digest_mode=digest_mode,
                curated_results=curated_results,
            )
            coverage_score = float(assessment["coverage_score"])
            gaps_remaining = list(assessment["gaps_remaining"])
            source_class_breakdown = dict(assessment["source_class_breakdown"])
            gap_queries = self._build_gap_queries(
                chapter_title=chapter_title or base_queries[0],
                objective=objective,
                gaps=gaps_remaining,
                digest_mode=digest_mode,
                max_queries=int(strategy["max_gap_queries_per_round"]),
            )
            newly_enqueued = self._enqueue_gap_queries(pending_queries, gap_queries, limit=resolved_query_cap)
            score_gain = coverage_score - previous_score
            curated_growth = len(curated_results) - previous_curated_count
            research_rounds.append(
                {
                    "round_index": round_index,
                    "executed_queries": list(round_queries),
                    "local_hits": round_local_hits,
                    "web_hits": round_web_hits,
                    "external_queries": list(dict.fromkeys(round_external_queries)),
                    "fallback_queries": list(dict.fromkeys(round_fallback_queries)),
                    "coverage_score": coverage_score,
                    "gaps_remaining": list(gaps_remaining),
                    "curated_source_count": int(curator_metadata.get("selected_count", len(curated_results))),
                    "document_count": len(documents),
                    "compression_mode": compression_mode,
                    "source_class_breakdown": source_class_breakdown,
                    "enqueued_gap_queries": list(newly_enqueued),
                    "score_gain": round(score_gain, 4),
                    "curated_growth": curated_growth,
                }
            )
            if coverage_score >= float(strategy["coverage_target"]) and not gaps_remaining:
                stop_reason = "coverage_target_met"
                break
            if not newly_enqueued and len(executed_queries) >= len(pending_queries):
                stop_reason = "gap_queue_exhausted"
                break
            if round_index > 1 and score_gain < float(strategy["min_score_gain"]) and curated_growth <= 0:
                stop_reason = "diminishing_returns"
                break

            previous_score = coverage_score
            previous_curated_count = len(curated_results)

        gap_queries_executed = dedupe_queries(
            [
                query
                for round_item in research_rounds
                for query in list(round_item.get("enqueued_gap_queries", []) or [])
            ],
            limit=resolved_query_cap,
        )
        purify_used = False
        if dense_context:
            purified_context, purify_used = await self._purify_material(
                dense_context=dense_context,
                chapter_title=chapter_title or base_queries[0],
                objective=objective,
                required_elements=list(required_elements or []),
                digest_mode=digest_mode,
                skillpack_guidance=skillpack_guidance,
                recommended_tool_tags=recommended_tool_tags,
            )
            dense_context = purified_context.strip() or dense_context

        return TracedExecutionResult(
            content=dense_context,
            sources=list(dict.fromkeys(item.url for item in curated_results if item.url)),
            metadata={
                "local_hits": local_hits,
                "web_hits": web_hits,
                "query_count": len(executed_queries),
                "base_queries": base_queries,
                "planned_queries": planned_queries,
                "gap_queries": gap_queries_executed,
                "fallback_queries": list(dict.fromkeys(fallback_queries)),
                "fallback_used": bool(fallback_queries),
                "executed_queries": executed_queries,
                "read_url_count": read_url_count,
                "document_count": len(documents),
                "requested_profile": resolved_retrieval_profile or "default",
                "applied_profile": resolved_retrieval_profile or "default",
                "requested_retrieval_profile": resolved_retrieval_profile,
                "applied_retrieval_profile": resolved_retrieval_profile or "default",
                "configured_retrievers": configured_retrievers,
                "active_retrievers": [local_retriever.name, *[retriever.name for retriever in other_retrievers]],
                "compression_mode": compression_mode,
                "purify_used": purify_used,
                "curated_source_count": curator_metadata.get("selected_count", len(curated_results)),
                "trusted_source_count": curator_metadata.get("trusted_source_count", 0),
                "local_source_count": curator_metadata.get("local_source_count", 0),
                "web_source_count": curator_metadata.get("web_source_count", 0),
                "unique_domain_count": curator_metadata.get("unique_domain_count", 0),
                "top_domains": curator_metadata.get("top_domains", {}),
                "retriever_stats": retriever_stats,
                "research_rounds": research_rounds,
                "research_round_count": len(research_rounds),
                "gaps_remaining": list(gaps_remaining),
                "coverage_score": coverage_score,
                "source_class_breakdown": self._classify_source_breakdown(curated_results),
                "stop_reason": stop_reason,
                "source_details": [item.to_dict() for item in curated_results],
                "selected_skillpacks": list(selected_skillpacks or []),
                "recommended_tool_tags": recommended_tool_tags,
            },
        )

    @traceable(name="DocGen：执行一轮章节检索", run_type="chain")
    async def _run_research_round(
        self,
        *,
        round_index: int,
        round_queries: list[str],
        search_domain: str,
        query_limit: int,
        settings,
        local_retriever,
        other_retrievers: list[Any],
        local_hits_total: int,
        web_hits_total: int,
        fallback_queries_total: list[str],
        executed_queries: list[str],
        retriever_stats: dict[str, dict[str, Any]],
        all_results: list[SearchResult],
        retrieval_started_at: float,
        retrieval_budget_s: float,
        provider_budget_s: float,
    ) -> dict[str, Any]:
        round_local_hits = 0
        round_web_hits = 0
        round_fallback_queries: list[str] = []
        round_external_queries: list[str] = []
        external_attempts = 0
        external_attempt_budget = max(1, min(2, len(round_queries))) if other_retrievers else 0

        for query in round_queries:
            executed_queries.append(query)
            local_results = self._filter_search_results(
                await self._search_with_budget(
                    local_retriever,
                    query=query,
                    max_results=query_limit,
                    provider_budget_s=provider_budget_s,
                    retrieval_started_at=retrieval_started_at,
                    retrieval_budget_s=retrieval_budget_s,
                )
            )
            self._record_retriever_call(
                retriever_stats,
                retriever_name=local_retriever.name,
                query=query,
                results=local_results,
            )
            local_hits_total += len(local_results)
            round_local_hits += len(local_results)
            combined_results = list(local_results)

            should_query_external = bool(other_retrievers) and (
                len(local_results) < settings.local_rag.min_results
                or external_attempts < external_attempt_budget
            )
            if should_query_external:
                external_attempts += 1
                round_external_queries.append(query)
                if len(local_results) < settings.local_rag.min_results:
                    fallback_queries_total.append(query)
                    round_fallback_queries.append(query)
                expanded_queries = enrich_queries_for_education([query], domain=search_domain)
                for retriever in other_retrievers:
                    for expanded_query in expanded_queries:
                        provider_results = self._filter_search_results(
                            await self._search_with_budget(
                                retriever,
                                query=expanded_query,
                                max_results=query_limit,
                                provider_budget_s=provider_budget_s,
                                retrieval_started_at=retrieval_started_at,
                                retrieval_budget_s=retrieval_budget_s,
                            )
                        )
                        self._record_retriever_call(
                            retriever_stats,
                            retriever_name=retriever.name,
                            query=expanded_query,
                            results=provider_results,
                        )
                        if provider_results:
                            web_hits_total += len(provider_results)
                            round_web_hits += len(provider_results)
                            combined_results.extend(provider_results)
                        if len(self._dedupe_results(combined_results)) >= query_limit:
                            break
                    if len(self._dedupe_results(combined_results)) >= query_limit:
                        break

            if len(local_results) < settings.local_rag.min_results and not should_query_external:
                fallback_queries_total.append(query)
                round_fallback_queries.append(query)

            all_results.extend(self._dedupe_results(combined_results, max_results=query_limit))

        return {
            "local_hits_total": local_hits_total,
            "web_hits_total": web_hits_total,
            "round_local_hits": round_local_hits,
            "round_web_hits": round_web_hits,
            "round_fallback_queries": round_fallback_queries,
            "round_external_queries": round_external_queries,
        }

    async def _search_with_budget(
        self,
        retriever,
        *,
        query: str,
        max_results: int,
        provider_budget_s: float,
        retrieval_started_at: float,
        retrieval_budget_s: float,
    ) -> list[SearchResult]:
        remaining = retrieval_budget_s - (time.monotonic() - retrieval_started_at)
        if remaining <= 0:
            return []
        try:
            return await asyncio.wait_for(
                retriever.traced_search(query, max_results=max_results),
                timeout=max(0.1, min(provider_budget_s, remaining)),
            )
        except TimeoutError:
            self.logger.warning(
                "docgen_retriever_timeout",
                retriever=retriever.name,
                query=query,
                timeout_s=min(provider_budget_s, max(0.1, remaining)),
            )
            return []
        except Exception as exc:
            self.logger.warning(
                "docgen_retriever_failed",
                retriever=retriever.name,
                query=query,
                error=str(exc),
            )
            return []

    async def _collect_documents(
        self,
        results: Iterable[SearchResult],
        *,
        page_cache: dict[str, ScrapedPage] | None = None,
        read_timeout_s: float | None = None,
    ) -> tuple[list[str], int]:
        documents: list[str] = []
        external_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for item in results:
            if item.url.startswith("local://"):
                text = item.to_text()
                if text.strip():
                    documents.append(text)
                continue
            if not item.url or item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            external_results.append(item)

        cache = page_cache if page_cache is not None else {}
        urls_to_fetch = [item.url for item in external_results if item.url not in cache]
        if urls_to_fetch:
            pages = await read_urls(
                urls_to_fetch,
                max_workers=min(len(urls_to_fetch), get_settings().docgen.io_parallelism),
                timeout_s=read_timeout_s,
            )
            for page in pages:
                cache[page.url] = page
        page_map = cache

        read_url_count = 0
        for item in external_results:
            page = page_map.get(item.url) or ScrapedPage(url=item.url, success=False, error="missing read page")
            if page.success and page.content.strip():
                read_url_count += 1
                title = page.title.strip() or item.title.strip() or item.url.strip()
                documents.append(f"# {title}\n\n{page.content.strip()}")
                continue
            if item.snippet.strip():
                documents.append(item.to_text())
        return documents, read_url_count

    async def _purify_material(
        self,
        *,
        dense_context: str,
        chapter_title: str,
        objective: str,
        required_elements: list[str],
        digest_mode: str,
        skillpack_guidance: str = "",
        recommended_tool_tags: list[str] | None = None,
    ) -> tuple[str, bool]:
        if not dense_context.strip():
            return "", False
        if len(dense_context) < 900 and not required_elements and not objective.strip():
            return dense_context, False

        llm_caller = self.context.resolve_llm_caller()
        try:
            response = await llm_caller(
                build_docgen_research_purify_messages(
                    dense_context=dense_context,
                    chapter_title=chapter_title,
                    objective=objective,
                    required_elements=required_elements,
                    digest_mode=digest_mode,
                    skillpack_guidance=skillpack_guidance,
                    recommended_tool_tags=recommended_tool_tags or [],
                ),
                task_type=TaskType.DOCGEN_LIGHT,
                model="light",
                extra_metadata=self.context.trace_metadata(
                    runtime_name=self.name,
                    research_stage="purify_material",
                ),
            )
        except Exception as exc:  # pragma: no cover - integration-heavy fallback
            self.logger.warning("research_material_purify_failed", error=str(exc), chapter_title=chapter_title)
            return dense_context, False

        if isinstance(response, str):
            cleaned = response.strip()
            if cleaned:
                return cleaned, True
        return dense_context, False

    def _filter_search_results(self, results: Iterable[SearchResult]) -> list[SearchResult]:
        filtered: list[SearchResult] = []
        for item in results:
            url = item.url.strip().lower()
            if url.startswith("local://"):
                filtered.append(item)
                continue
            if url and any(marker in url for marker in _LOW_VALUE_SOURCE_MARKERS):
                continue
            filtered.append(item)
        return filtered

    def _dedupe_results(
        self,
        results: Iterable[SearchResult],
        *,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[str] = set()
        for item in results:
            key = item.url.strip() or f"{item.title.strip()}::{item.snippet.strip()[:120]}"
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if max_results is not None and len(deduped) >= max_results:
                break
        return deduped

    def _record_retriever_call(
        self,
        stats_map: dict[str, dict[str, Any]],
        *,
        retriever_name: str,
        query: str,
        results: list[SearchResult],
    ) -> None:
        entry = stats_map.setdefault(
            retriever_name,
            {
                "query_count": 0,
                "result_count": 0,
                "queries": [],
            },
        )
        entry["query_count"] = int(entry.get("query_count", 0) or 0) + 1
        entry["result_count"] = int(entry.get("result_count", 0) or 0) + len(results)
        queries = list(entry.get("queries", []))
        if query not in queries:
            queries.append(query)
        entry["queries"] = queries[:8]

    def _resolve_strategy(self, digest_mode: str) -> dict[str, Any]:
        normalized = str(digest_mode or "").strip().lower()
        return dict(_MODE_RESEARCH_STRATEGIES.get(normalized, _MODE_RESEARCH_STRATEGIES["systematic"]))

    def _take_round_queries(
        self,
        pending_queries: list[str],
        *,
        executed_queries: list[str],
        limit: int,
    ) -> list[str]:
        executed = {query.casefold() for query in executed_queries if str(query).strip()}
        round_queries: list[str] = []
        for query in pending_queries:
            normalized = str(query or "").strip()
            if not normalized or normalized.casefold() in executed:
                continue
            round_queries.append(normalized)
            if len(round_queries) >= max(1, limit):
                break
        return round_queries

    def _enqueue_gap_queries(self, pending_queries: list[str], gap_queries: list[str], *, limit: int) -> list[str]:
        existing = {query.casefold() for query in pending_queries if str(query).strip()}
        newly_enqueued: list[str] = []
        for query in gap_queries:
            normalized = str(query or "").strip()
            if not normalized or normalized.casefold() in existing:
                continue
            pending_queries.append(normalized)
            existing.add(normalized.casefold())
            newly_enqueued.append(normalized)
            if len(pending_queries) >= max(1, limit):
                break
        return newly_enqueued

    def _assess_coverage(
        self,
        *,
        dense_context: str,
        objective: str,
        required_elements: list[str],
        digest_mode: str,
        curated_results: list[SearchResult],
    ) -> dict[str, Any]:
        normalized_context = self._normalize_text_blob(dense_context)
        normalized_titles = self._normalize_text_blob("\n".join(item.title for item in curated_results))
        coverage_targets = self._coverage_targets(
            required_elements=required_elements,
            objective=objective,
            digest_mode=digest_mode,
        )
        if not coverage_targets:
            return {
                "coverage_score": 1.0,
                "gaps_remaining": [],
                "source_class_breakdown": self._classify_source_breakdown(curated_results),
            }
        hits = 0
        gaps_remaining: list[str] = []
        for target in coverage_targets:
            needle = self._normalize_text_blob(target)
            if needle and (needle in normalized_context or needle in normalized_titles):
                hits += 1
                continue
            gaps_remaining.append(target)
        coverage_score = round(hits / max(1, len(coverage_targets)), 4)
        return {
            "coverage_score": coverage_score,
            "gaps_remaining": gaps_remaining,
            "source_class_breakdown": self._classify_source_breakdown(curated_results),
        }

    def _coverage_targets(
        self,
        *,
        required_elements: list[str],
        objective: str,
        digest_mode: str,
    ) -> list[str]:
        targets = list(required_elements or [])
        targets.extend(self._extract_objective_terms(objective))
        if not targets:
            return []
        return dedupe_queries(targets, limit=8)

    def _extract_objective_terms(self, objective: str) -> list[str]:
        fragments: list[str] = []
        for item in _TERM_SPLIT_RE.split(str(objective or "").strip()):
            normalized = item.strip()
            if len(normalized) < 2:
                continue
            fragments.append(normalized)
        return fragments[:4]

    def _build_gap_queries(
        self,
        *,
        chapter_title: str,
        objective: str,
        gaps: list[str],
        digest_mode: str,
        max_queries: int,
    ) -> list[str]:
        normalized_mode = str(digest_mode or "").strip().lower()
        suffixes = (
            ["高频题型", "易错点", "典型例题"]
            if normalized_mode == "sprint"
            else ["定义", "推导", "联系", "典型例子"]
        )
        seeds = gaps[: max(1, max_queries)]
        if objective.strip():
            seeds.extend(self._extract_objective_terms(objective)[:1])
        gap_queries: list[str] = []
        for index, seed in enumerate(seeds):
            gap_queries.append(f"{chapter_title} {seed} {suffixes[index % len(suffixes)]}")
        return dedupe_queries(gap_queries, limit=max(1, max_queries))

    def _classify_source_breakdown(self, results: list[SearchResult]) -> dict[str, int]:
        breakdown = {
            "local": 0,
            "academic": 0,
            "institutional": 0,
            "community": 0,
            "general_web": 0,
        }
        for item in results:
            bucket = self._classify_source(item)
            breakdown[bucket] = breakdown.get(bucket, 0) + 1
        return {key: value for key, value in breakdown.items() if value > 0}

    def _classify_source(self, item: SearchResult) -> str:
        url = str(item.url or "").strip().lower()
        source = str(item.source or "").strip().lower()
        if url.startswith("local://") or source == "local_rag":
            return "local"
        domain = urlparse(url).netloc.strip().lower()
        if any(marker in domain for marker in (".edu", ".ac.", "arxiv.org", "semanticscholar", "semantic_scholar")):
            return "academic"
        if any(marker in domain for marker in (".gov", ".org", "ocw.", "xuetangx.com", "icourse163.org")):
            return "institutional"
        if any(marker in domain for marker in ("zhihu.com", "csdn.net", "reddit.com", "stackexchange.com")):
            return "community"
        return "general_web"

    def _normalize_text_blob(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).casefold()


__all__ = ["DocGenChapterContextRuntime"]
