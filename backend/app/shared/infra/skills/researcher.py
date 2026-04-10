"""Research conductor skill."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.shared.infra.config import get_settings
from app.shared.infra.model_router import TaskType
from app.shared.infra.search.factory import get_retrievers_for_subject
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.skills.base import BaseSkill, SkillResult
from app.shared.infra.skills.context_manager import ContextManager
from app.shared.infra.skills.source_curator import SourceCurator
from app.shared.infra.tools.builtin.query_processing import (
    build_research_focus_text,
    dedupe_queries,
    enrich_queries_for_education,
    generate_sub_queries,
)
from app.shared.infra.tools.builtin.web_scraping import scrape_urls
from app.workflows.digest.prompts import build_docgen_research_purify_messages

_LOW_VALUE_SOURCE_MARKERS = (
    "baidu.com/zhidao",
    "360doc.com",
    "docin.com",
)


class ResearchConductor(BaseSkill):
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
        search_domain: str = "zh",
        max_results_per_query: int | None = None,
    ) -> SkillResult:
        settings = get_settings()
        query_limit = max_results_per_query or settings.search_max_results_per_query
        base_queries = dedupe_queries(
            queries,
            limit=max(1, int(settings.docgen_max_research_queries)),
        )
        if not base_queries and str(chapter_title).strip():
            base_queries = [str(chapter_title).strip()]
        if not base_queries:
            return SkillResult(metadata={"local_hits": 0, "web_hits": 0, "query_count": 0})

        focus_text = build_research_focus_text(
            title=chapter_title or base_queries[0],
            objective=objective,
            required_elements=required_elements,
            digest_mode=digest_mode,
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
            max_queries=max(1, int(settings.docgen_max_research_queries)),
            domain=search_domain,
            llm_caller=self.context.resolve_llm_caller(),
            extra_metadata=self.context.trace_metadata(
                skill_name=self.name,
                research_stage="plan_sub_queries",
            ),
        )
        research_queries = dedupe_queries(
            [*base_queries, *planned_queries],
            limit=max(1, int(settings.docgen_max_research_queries)),
        )
        local_retriever = LocalRAGRetriever(subject=local_rag_subject, local_sections=local_sections)
        other_retrievers = [
            retriever
            for retriever in get_retrievers_for_subject(subject=local_rag_subject, local_sections=local_sections)
            if retriever.name != local_retriever.name
        ]
        compressor = ContextManager(self.context)
        curator = SourceCurator(self.context)

        all_results: list[SearchResult] = []
        local_hits = 0
        web_hits = 0
        fallback_queries: list[str] = []
        retriever_stats: dict[str, dict[str, Any]] = {}

        for query in research_queries:
            local_results = self._filter_search_results(
                await local_retriever.traced_search(query, max_results=query_limit)
            )
            self._record_retriever_call(
                retriever_stats,
                retriever_name=local_retriever.name,
                query=query,
                results=local_results,
            )
            local_hits += len(local_results)
            combined_results = list(local_results)

            if len(local_results) < settings.local_rag_min_results:
                fallback_queries.append(query)
                expanded_queries = enrich_queries_for_education([query], domain=search_domain)
                for retriever in other_retrievers:
                    for expanded_query in expanded_queries:
                        provider_results = self._filter_search_results(
                            await retriever.traced_search(expanded_query, max_results=query_limit)
                        )
                        self._record_retriever_call(
                            retriever_stats,
                            retriever_name=retriever.name,
                            query=expanded_query,
                            results=provider_results,
                        )
                        if provider_results:
                            web_hits += len(provider_results)
                            combined_results.extend(provider_results)
                        if len(self._dedupe_results(combined_results)) >= query_limit:
                            break
                    if len(self._dedupe_results(combined_results)) >= query_limit:
                        break

            all_results.extend(self._dedupe_results(combined_results, max_results=query_limit))

        merged_results = self._dedupe_results(
            self._filter_search_results(all_results),
            max_results=max(query_limit * max(1, len(research_queries)), query_limit),
        )
        curated_results, curator_metadata = await curator.curate_sources(
            query=focus_text or base_queries[0],
            sources=merged_results,
            max_results=max(query_limit * 2, len(base_queries) * 3),
        )
        documents, scraped_url_count = await self._collect_documents(curated_results)
        if not documents:
            documents = [item.to_text() for item in curated_results if item.to_text().strip()]

        compression_result = await compressor.run(
            query=focus_text or base_queries[0],
            focus_terms=list(required_elements or []),
            documents=documents,
            max_results=8,
            max_total_chars=6000 if digest_mode == "systematic" else 4200,
        )
        dense_context = compression_result.content.strip()
        purify_used = False
        if dense_context:
            purified_context, purify_used = await self._purify_material(
                dense_context=dense_context,
                chapter_title=chapter_title or base_queries[0],
                objective=objective,
                required_elements=list(required_elements or []),
                digest_mode=digest_mode,
            )
            dense_context = purified_context.strip() or dense_context

        return SkillResult(
            content=dense_context,
            sources=list(dict.fromkeys(item.url for item in curated_results if item.url)),
            metadata={
                "local_hits": local_hits,
                "web_hits": web_hits,
                "query_count": len(research_queries),
                "base_queries": base_queries,
                "planned_queries": planned_queries,
                "fallback_queries": list(dict.fromkeys(fallback_queries)),
                "fallback_used": bool(fallback_queries),
                "executed_queries": research_queries,
                "scraped_url_count": scraped_url_count,
                "document_count": len(documents),
                "compression_mode": compression_result.metadata.get("compression_mode", "empty"),
                "purify_used": purify_used,
                "curated_source_count": curator_metadata.get("selected_count", len(curated_results)),
                "trusted_source_count": curator_metadata.get("trusted_source_count", 0),
                "local_source_count": curator_metadata.get("local_source_count", 0),
                "web_source_count": curator_metadata.get("web_source_count", 0),
                "unique_domain_count": curator_metadata.get("unique_domain_count", 0),
                "top_domains": curator_metadata.get("top_domains", {}),
                "retriever_stats": retriever_stats,
                "source_details": [item.to_dict() for item in curated_results],
            },
        )

    async def _collect_documents(self, results: Iterable[SearchResult]) -> tuple[list[str], int]:
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

        pages = await scrape_urls([item.url for item in external_results])
        page_map = {page.url: page for page in pages}

        scraped_url_count = 0
        for item in external_results:
            page = page_map.get(item.url) or ScrapedPage(url=item.url, success=False, error="missing scraped page")
            if page.success and page.content.strip():
                scraped_url_count += 1
                title = page.title.strip() or item.title.strip() or item.url.strip()
                documents.append(f"# {title}\n\n{page.content.strip()}")
                continue
            if item.snippet.strip():
                documents.append(item.to_text())
        return documents, scraped_url_count

    async def _purify_material(
        self,
        *,
        dense_context: str,
        chapter_title: str,
        objective: str,
        required_elements: list[str],
        digest_mode: str,
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
                ),
                task_type=TaskType.DOCGEN_LIGHT,
                extra_metadata=self.context.trace_metadata(
                    skill_name=self.name,
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


__all__ = ["ResearchConductor"]
