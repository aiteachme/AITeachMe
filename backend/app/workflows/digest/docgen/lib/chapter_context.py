"""Workflow-local chapter context runtime for digest DocGen."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from app.shared.infra.settings import get_settings
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.search.defaults import (
    DEFAULT_SEARCH_MAX_RESULTS_PER_QUERY,
    DEFAULT_SEARCH_PROVIDER_TIMEOUT_S,
)
from app.shared.infra.search import ContextCompressor, SourceCurator
from app.shared.infra.search.factory import get_configured_retriever_names, get_retrievers_for_course
from app.shared.infra.search.local_sufficiency import (
    DEFAULT_EFFECTIVE_LOCAL_SCORE,
    effective_local_result_count,
)
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.tools.builtin.web_reading import read_urls
from app.workflows.digest.docgen.lib.defaults import (
    DEFAULT_DOCGEN_IO_PARALLELISM,
    DEFAULT_DOCGEN_MAX_RESEARCH_QUERIES,
    DEFAULT_DOCGEN_READ_TIMEOUT_S,
    DEFAULT_DOCGEN_RETRIEVAL_TIMEOUT_S,
)
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile
from app.workflows.digest.docgen.lib.query_planning import (
    build_research_focus_text,
    dedupe_queries,
    enrich_queries_for_retriever,
    generate_sub_queries,
)

_TERM_SPLIT_RE = re.compile(r"[，。；：、,.!?\n\r/（）()\-]+")
_SPECIALIZED_RETRIEVERS = {
    "zh_wikibooks",
    "zh_wikiversity",
    "zh_wikipedia",
    "zh_wiktionary",
    "wikipedia",
}
_ACADEMIC_RETRIEVERS = {
    "arxiv",
    "semantic_scholar",
    "pubmed_central",
}
_BROAD_WEB_RETRIEVERS = {
    "baidu_ai_search",
    "bing",
    "bocha",
    "brave",
    "duckduckgo",
    "exa",
    "google_cse",
    "jina_search",
    "mcp_search",
    "openrouter_search",
    "perplexity",
    "searchapi",
    "searxng",
    "serpapi",
    "serper",
    "tavily",
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
        local_rag_course_id: str | None = None,
        local_sections: list[Any] | None = None,
        chapter_title: str = "",
        objective: str = "",
        required_elements: list[str] | None = None,
        digest_mode: str = "",
        retrieval_profile: str | None = None,
        search_domain: str = "zh",
        max_results_per_query: int | None = None,
        max_research_rounds: int | None = None,
        max_context_chars: int | None = None,
        query_cap: int | None = None,
        queries_per_round: int | None = None,
        max_gap_queries_per_round: int | None = None,
        max_external_queries: int | None = None,
        plan_subqueries: bool = True,
    ) -> TracedExecutionResult:
        """执行单章研究上下文构建。

        这一步负责把章节任务里的检索意图变成可写作的 dense_context：
        先规划完整子查询，再按预算并发执行本地 RAG 和外部检索，随后打开网页、
        压缩材料。返回值是给 writer 和
        evidence/claim 账本消费的研究包，而不是最终正文。
        """

        settings = get_settings()
        query_limit = max_results_per_query or DEFAULT_SEARCH_MAX_RESULTS_PER_QUERY
        strategy = self._resolve_strategy(digest_mode)
        del max_research_rounds, queries_per_round, max_gap_queries_per_round
        if max_context_chars is not None:
            strategy["max_total_chars"] = max(1000, int(max_context_chars))
        resolved_query_cap = max(
            max(1, int(DEFAULT_DOCGEN_MAX_RESEARCH_QUERIES)),
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
        planned_queries = (
            await generate_sub_queries(
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
            )
            if plan_subqueries
            else []
        )
        research_queries = dedupe_queries([*base_queries, *planned_queries], limit=resolved_query_cap)
        resolved_retrieval_profile = str(retrieval_profile or self.context.retrieval_profile or "").strip()
        external_search_enabled = bool(settings.docgen.allow_external_search)
        local_retriever = LocalRAGRetriever(course_id=local_rag_course_id, local_sections=local_sections)
        other_retrievers = self._balance_external_retrievers(
            [
                retriever
                for retriever in get_retrievers_for_course(
                    course_id=local_rag_course_id,
                    local_sections=local_sections,
                    profile=resolved_retrieval_profile or None,
                    include_external=external_search_enabled,
                )
                if retriever.name != local_retriever.name
                and retriever.name in self._docgen_external_retriever_allowlist()
            ]
        )
        configured_retrievers = get_configured_retriever_names(
            profile=resolved_retrieval_profile or None,
            include_local_rag=bool(local_rag_course_id or local_sections),
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
        stop_reason = "query_plan_executed"
        curated_results: list[SearchResult] = []
        curator_metadata: dict[str, Any] = {}
        documents: list[str] = []
        dense_context = ""
        compression_mode = "empty"
        read_url_count = 0
        page_cache: dict[str, ScrapedPage] = {}
        retrieval_started_at = time.monotonic()
        retrieval_budget_s = max(1.0, float(DEFAULT_DOCGEN_RETRIEVAL_TIMEOUT_S))
        provider_budget_s = max(0.5, float(DEFAULT_SEARCH_PROVIDER_TIMEOUT_S))

        if time.monotonic() - retrieval_started_at < retrieval_budget_s and research_queries:
            round_result = await self._run_research_round(
                round_index=1,
                round_queries=research_queries,
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
                external_query_cap=max_external_queries,
            )
            local_hits = int(round_result["local_hits_total"])
            web_hits = int(round_result["web_hits_total"])
            round_local_hits = int(round_result["round_local_hits"])
            round_web_hits = int(round_result["round_web_hits"])
            round_fallback_queries = list(round_result["round_fallback_queries"])
            round_external_queries = list(round_result.get("round_external_queries", []) or [])

            merged_results = self._dedupe_results(
                all_results,
                max_results=max(query_limit * max(1, len(executed_queries)), query_limit),
            )
            # Source relevance must be measured against the concise query that
            # produced the candidates.  The full teaching focus can exceed one
            # hundred characters and used to dilute every lexical match to zero.
            curated_results, curator_metadata = await curator.curate_sources(
                query=base_queries[0],
                sources=merged_results,
                max_results=max(query_limit * 2, len(executed_queries) * 2),
            )
            documents, read_url_count = await self._collect_documents(
                curated_results,
                page_cache=page_cache,
                read_timeout_s=float(DEFAULT_DOCGEN_READ_TIMEOUT_S),
                focus_text=focus_text or base_queries[0],
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
            research_rounds.append(
                {
                    "round_index": 1,
                    "executed_queries": list(research_queries),
                    "local_hits": round_local_hits,
                    "web_hits": round_web_hits,
                    "external_queries": list(dict.fromkeys(round_external_queries)),
                    "fallback_queries": list(dict.fromkeys(round_fallback_queries)),
                    "coverage_score": 0.0,
                    "gaps_remaining": [],
                    "curated_source_count": int(curator_metadata.get("selected_count", len(curated_results))),
                    "document_count": len(documents),
                    "compression_mode": compression_mode,
                    "source_class_breakdown": self._classify_source_breakdown(curated_results),
                    "enqueued_gap_queries": [],
                    "score_gain": 0.0,
                    "curated_growth": len(curated_results),
                }
            )
        elif research_queries:
            stop_reason = "retrieval_budget_exhausted"
        return TracedExecutionResult(
            content=dense_context,
            sources=list(dict.fromkeys(item.url for item in curated_results if item.url)),
            metadata={
                "local_hits": local_hits,
                "web_hits": web_hits,
                "query_count": len(executed_queries),
                "base_queries": base_queries,
                "planned_queries": planned_queries,
                "gap_queries": [],
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
                "purify_used": False,
                "curated_source_count": curator_metadata.get("selected_count", len(curated_results)),
                "trusted_source_count": curator_metadata.get("trusted_source_count", 0),
                "local_source_count": curator_metadata.get("local_source_count", 0),
                "web_source_count": curator_metadata.get("web_source_count", 0),
                "unique_domain_count": curator_metadata.get("unique_domain_count", 0),
                "top_domains": curator_metadata.get("top_domains", {}),
                "retriever_stats": retriever_stats,
                "research_rounds": research_rounds,
                "research_round_count": len(research_rounds),
                "gaps_remaining": [],
                "coverage_score": 0.0,
                "source_class_breakdown": self._classify_source_breakdown(curated_results),
                "stop_reason": stop_reason,
                "source_details": [item.to_dict() for item in curated_results],
            },
        )

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
        external_query_cap: int | None = None,
    ) -> dict[str, Any]:
        """执行一轮章节检索并累计检索状态。

        每轮会用同一组章节检索词并行运行本地 RAG 与有限外部检索校准；结果会追加
        到 all_results，并更新 query、hit、retriever_stats 等跨轮累计状态。
        """

        round_local_hits = 0
        round_web_hits = 0
        round_fallback_queries: list[str] = []
        round_external_queries: list[str] = []

        async def _search_and_filter(retriever, *, query: str) -> list[SearchResult]:
            return await self._search_with_budget(
                retriever,
                query=query,
                max_results=query_limit,
                provider_budget_s=provider_budget_s,
                retrieval_started_at=retrieval_started_at,
                retrieval_budget_s=retrieval_budget_s,
            )

        results_by_query: dict[str, list[SearchResult]] = {}
        external_jobs: list[tuple[str, Any, str]] = []
        external_query_budget = (
            min(
                max(1, int(external_query_cap or 2)),
                len(round_queries),
            )
            if other_retrievers
            else 0
        )
        for query in round_queries[:external_query_budget]:
            query_jobs = self._build_external_search_jobs(
                base_query=query,
                retrievers=other_retrievers,
                search_domain=search_domain,
                job_limit=max(1, min(query_limit, int(DEFAULT_DOCGEN_IO_PARALLELISM))),
            )
            if query_jobs:
                round_external_queries.append(query)
                external_jobs.extend(query_jobs)

        search_semaphore = asyncio.Semaphore(max(1, int(DEFAULT_DOCGEN_IO_PARALLELISM)))

        async def _run_external_job(job: tuple[str, Any, str]) -> tuple[str, Any, str, list[SearchResult]]:
            base_query, retriever, expanded_query = job
            async with search_semaphore:
                provider_results = await _search_and_filter(retriever, query=expanded_query)
            return base_query, retriever, expanded_query, provider_results

        local_searches, external_results = await asyncio.gather(
            asyncio.gather(
                *[
                    _search_and_filter(local_retriever, query=query)
                    for query in round_queries
                ]
            ),
            asyncio.gather(*[_run_external_job(job) for job in external_jobs]),
        )

        for query, local_results in zip(round_queries, local_searches, strict=False):
            executed_queries.append(query)
            self._record_retriever_call(
                retriever_stats,
                retriever_name=local_retriever.name,
                query=query,
                results=local_results,
            )
            local_hits_total += len(local_results)
            round_local_hits += len(local_results)
            results_by_query[query] = list(local_results)

            effective_local_hits = effective_local_result_count(
                local_results,
                min_score=max(
                    float(settings.rag.similarity_threshold or 0.0),
                    DEFAULT_EFFECTIVE_LOCAL_SCORE,
                ),
            )
            if effective_local_hits == 0:
                fallback_queries_total.append(query)
                round_fallback_queries.append(query)

        for base_query, retriever, expanded_query, provider_results in external_results:
            self._record_retriever_call(
                retriever_stats,
                retriever_name=retriever.name,
                query=expanded_query,
                results=provider_results,
            )
            if not provider_results:
                continue
            web_hits_total += len(provider_results)
            round_web_hits += len(provider_results)
            results_by_query.setdefault(base_query, []).extend(provider_results)

        for query in round_queries:
            combined_results = results_by_query.get(query, [])
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
        if remaining < 1.2:
            self.logger.info(
                "docgen_retriever_skipped_budget_low",
                retriever=retriever.name,
                query=query,
                remaining_s=round(max(0.0, remaining), 3),
            )
            return []
        try:
            return await asyncio.wait_for(
                retriever.traced_search(query, max_results=max_results),
                timeout=max(0.1, min(provider_budget_s, remaining)),
            )
        except TimeoutError:
            self.logger.info(
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
        focus_text: str = "",
    ) -> tuple[list[str], int]:
        """把检索结果转换成可压缩文档。

        local:// 结果直接使用切片文本；外部 URL 先通过 reader 打开正文。
        如果 reader 失败但搜索 snippet 可用，只保留来源质量和相关性足够的降级材料。
        """

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
            domain = urlparse(item.url).netloc.lower()
            if "wikipedia.org" in domain:
                text = item.to_text()
                if text.strip():
                    documents.append(text)
                continue
            seen_urls.add(item.url)
            external_results.append(item)

        cache = page_cache if page_cache is not None else {}
        urls_to_fetch = [item.url for item in external_results if item.url not in cache]
        if urls_to_fetch:
            pages = await read_urls(
                urls_to_fetch,
                max_workers=min(len(urls_to_fetch), DEFAULT_DOCGEN_IO_PARALLELISM),
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
            if item.snippet.strip() and self._should_keep_snippet_fallback(item, focus_text=focus_text):
                documents.append(item.to_text())
        return documents, read_url_count

    def _result_rank_key(self, item: SearchResult) -> tuple[int, float, int, str]:
        source_class = self._classify_source(item)
        class_rank = {
            "local": 4,
            "academic": 3,
            "institutional": 2,
            "general_web": 1,
        }.get(source_class, 0)
        return (
            class_rank,
            max(0.0, float(item.score or 0.0)),
            len(str(item.snippet or "")),
            str(item.title or "").casefold(),
        )

    def _dedupe_results(
        self,
        results: Iterable[SearchResult],
        *,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[str] = set()
        ranked = sorted(list(results), key=self._result_rank_key, reverse=True)
        for item in ranked:
            key = item.url.strip() or f"{item.title.strip()}::{item.snippet.strip()[:120]}"
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if max_results is not None and len(deduped) >= max_results:
                break
        return deduped

    def _should_keep_snippet_fallback(self, item: SearchResult, *, focus_text: str = "") -> bool:
        source_class = self._classify_source(item)
        if source_class in {"local", "academic", "institutional"}:
            return True
        snippet = str(item.snippet or "").strip()
        if len(snippet) < 60:
            return False
        if float(item.score or 0.0) >= 0.8:
            return True
        if not focus_text.strip():
            return False
        focus_terms = [
            self._normalize_text_blob(term)
            for term in _TERM_SPLIT_RE.split(focus_text)
            if len(self._normalize_text_blob(term)) >= 2
        ]
        haystack = self._normalize_text_blob(f"{item.title}\n{item.snippet}")
        hits = sum(1 for term in focus_terms if term and term in haystack)
        return hits >= max(2, int(len(focus_terms) * 0.4 + 0.5))

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

    def _docgen_external_retriever_allowlist(self) -> set[str]:
        # Keep DocGen web research stable and low-noise while still honoring
        # configured educational profiles. Community-style site wrappers such
        # as Zhihu/Baidu Baike are intentionally excluded from chapter source
        # reading; broad web providers may still surface those pages at lower
        # rank if they are genuinely relevant.
        return {
            "zh_wikibooks",
            "zh_wikiversity",
            "zh_wikipedia",
            "zh_wiktionary",
            "bocha",
            "tavily",
            "brave",
            "exa",
            "bing",
            "jina_search",
            "google_cse",
            "searchapi",
            "serpapi",
            "serper",
            "perplexity",
            "openrouter_search",
            "baidu_ai_search",
            "searxng",
            "wikipedia",
            "arxiv",
            "semantic_scholar",
            "pubmed_central",
            "mcp_search",
            "duckduckgo",
        }

    def _balance_external_retrievers(self, retrievers: list[Any]) -> list[Any]:
        """Interleave retrievers with broad web sources first."""

        buckets: list[list[Any]] = [[], [], [], []]
        for retriever in retrievers:
            name = str(getattr(retriever, "name", "") or "").strip().lower()
            if name in _BROAD_WEB_RETRIEVERS:
                buckets[0].append(retriever)
            elif name in _ACADEMIC_RETRIEVERS:
                buckets[1].append(retriever)
            elif name in _SPECIALIZED_RETRIEVERS:
                buckets[2].append(retriever)
            else:
                buckets[3].append(retriever)

        balanced: list[Any] = []
        max_bucket_size = max((len(bucket) for bucket in buckets), default=0)
        for index in range(max_bucket_size):
            for bucket in buckets:
                if index < len(bucket):
                    balanced.append(bucket[index])
        return balanced

    def _build_external_search_jobs(
        self,
        *,
        base_query: str,
        retrievers: list[Any],
        search_domain: str,
        job_limit: int,
    ) -> list[tuple[str, Any, str]]:
        """Build fair external search jobs without letting query variants crowd out providers."""

        if not retrievers:
            return []
        per_retriever_queries = [
            (
                retriever,
                enrich_queries_for_retriever(
                    [base_query],
                    domain=search_domain,
                    retriever_name=str(getattr(retriever, "name", "") or ""),
                ),
            )
            for retriever in retrievers
        ]
        jobs: list[tuple[str, Any, str]] = []
        seen: set[tuple[str, str]] = set()
        max_query_depth = max((len(queries) for _retriever, queries in per_retriever_queries), default=0)
        limit = max(1, int(job_limit or 1))
        for query_index in range(max_query_depth):
            for retriever, queries in per_retriever_queries:
                if query_index >= len(queries):
                    continue
                expanded_query = queries[query_index]
                key = (str(getattr(retriever, "name", "") or ""), expanded_query.casefold())
                if key in seen:
                    continue
                seen.add(key)
                jobs.append((base_query, retriever, expanded_query))
                if len(jobs) >= limit:
                    return jobs
        return jobs

    def _resolve_strategy(self, digest_mode: str) -> dict[str, Any]:
        return dict(get_docgen_mode_profile(digest_mode).research_strategy())

    def _classify_source_breakdown(self, results: list[SearchResult]) -> dict[str, int]:
        breakdown = {
            "local": 0,
            "academic": 0,
            "institutional": 0,
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
        if source in _ACADEMIC_RETRIEVERS or domain.endswith(".edu") or ".edu." in domain or ".ac." in domain:
            return "academic"
        if (
            source in _SPECIALIZED_RETRIEVERS
            or domain.endswith(".gov")
            or ".gov." in domain
            or domain.endswith(".org")
            or ".org." in domain
        ):
            return "institutional"
        return "general_web"

    def _normalize_text_blob(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).casefold()


__all__ = ["DocGenChapterContextRuntime"]
