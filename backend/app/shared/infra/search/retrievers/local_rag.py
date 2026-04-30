"""Local RAG retriever with a section-based fallback."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any
import re
import structlog

from app.shared.infra.search.knowledge import RetrievedChunk
from app.shared.infra.search.api import get_knowledge_search_notice, search_knowledge
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_CJK_CHUNK_RE = re.compile(r"[\u3400-\u9fff]+")
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{1,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    normalized = str(text or "").lower()
    tokens: set[str] = set()

    for match in _LATIN_TOKEN_RE.finditer(normalized):
        token = match.group(0).strip("._+-")
        if len(token) > 1:
            tokens.add(token)

    for match in _CJK_CHUNK_RE.finditer(normalized):
        chunk = match.group(0).strip()
        if len(chunk) < 2:
            continue
        tokens.add(chunk)
        max_ngram = min(4, len(chunk))
        for size in range(2, max_ngram + 1):
            for index in range(0, len(chunk) - size + 1):
                tokens.add(chunk[index : index + size])

    return sorted(tokens)


class LocalRAGRetriever(BaseRetriever):
    aliases = ("rag",)
    cacheable = False

    def __init__(self, *, course_id: str | None = None, local_sections: list[Any] | None = None) -> None:
        self.course_id = (course_id or "").strip()
        self.local_sections = list(local_sections or [])
        self._vector_search_available: bool | None = None
        self._vector_search_notice: str | None = None
        self._vector_notice_logged = False

    @property
    def name(self) -> str:
        return "local_rag"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        count = clamp_max_results(max_results, upper=50)

        should_try_vector = bool(self.course_id)
        if should_try_vector and self.local_sections:
            should_try_vector = await self._refresh_vector_search_availability()
        vector_results: list[SearchResult] = []
        if should_try_vector and self.course_id:
            try:
                vector_chunks = await search_knowledge(
                    normalized_query,
                    self.course_id,
                    top_k=count * 2,
                )
            except Exception as exc:
                logger.warning(
                    "local_rag_vector_search_failed",
                    course_id=self.course_id,
                    query_len=len(normalized_query),
                    error=str(exc),
                )
                vector_chunks = []
            vector_results = self._from_chunks(vector_chunks)

        section_results = (
            self._section_fallback(normalized_query, max_results=count * 2)
            if self.local_sections
            else []
        )
        return self._fuse_ranked_results(
            vector_results=vector_results,
            section_results=section_results,
            max_results=count,
        )

    async def _refresh_vector_search_availability(self) -> bool:
        if self._vector_search_available is not None:
            return self._vector_search_available

        notice = await get_knowledge_search_notice(self.course_id)
        self._vector_search_notice = notice
        self._vector_search_available = notice is None
        if notice and not self._vector_notice_logged:
            logger.info(
                "local_rag_vector_search_bypassed",
                course_id=self.course_id,
                reason=notice,
                fallback="section_fallback",
            )
            self._vector_notice_logged = True
        return self._vector_search_available

    def _from_chunks(self, chunks: list[RetrievedChunk]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for chunk in chunks:
            header = chunk.header_path.strip() or chunk.title.strip() or f"Chunk {chunk.chunk_id}"
            snippet = chunk.content.strip()[:500]
            results.append(
                SearchResult(
                    url=f"local://chunk/{chunk.chunk_id}",
                    title=header,
                    snippet=snippet,
                    score=float(chunk.score),
                    source=self.name,
                )
            )
        return results

    def _section_fallback(self, query: str, *, max_results: int) -> list[SearchResult]:
        query_tokens = Counter(_tokenize(query))
        if not query_tokens:
            return []
        scored: list[tuple[float, SearchResult]] = []
        for index, section in enumerate(self.local_sections):
            title = str(getattr(section, "title", "") or section.get("title", ""))
            content = str(
                getattr(section, "normalized_content", "")
                or getattr(section, "content", "")
                or section.get("normalized_content", "")
                or section.get("content", "")
            )
            if not content.strip():
                continue
            text_tokens = Counter(_tokenize(f"{title} {content[:1200]}"))
            overlap = sum((query_tokens & text_tokens).values())
            if overlap <= 0:
                continue
            score = overlap / max(1, len(query_tokens))
            scored.append(
                (
                    score,
                    SearchResult(
                        url=f"local://section/{index}",
                        title=title or f"Section {index + 1}",
                        snippet=content[:500],
                        score=score,
                        source=self.name,
                    ),
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1].title))
        return [item for _, item in scored[:max_results]]

    def _dedupe_key(self, item: SearchResult) -> str:
        local_text_key = re.sub(
            r"\s+",
            "",
            f"{item.title.strip()}::{item.snippet.strip()[:180]}",
        ).casefold()
        if item.url.startswith("local://") and local_text_key:
            return local_text_key
        return item.url.strip() or local_text_key

    def _fuse_ranked_results(
        self,
        *,
        vector_results: list[SearchResult],
        section_results: list[SearchResult],
        max_results: int,
    ) -> list[SearchResult]:
        fused: dict[str, tuple[SearchResult, float, set[str]]] = {}

        def _add(results: list[SearchResult], *, source_name: str, weight: float) -> None:
            for rank, item in enumerate(results):
                key = self._dedupe_key(item)
                if not key:
                    continue
                raw_score = max(0.0, float(item.score or 0.0))
                score = weight / (60.0 + rank + 1.0) + min(raw_score, 1.0) * 0.05
                candidate = replace(item, score=score, source=self.name)
                existing = fused.get(key)
                if existing is None:
                    fused[key] = (candidate, score, {source_name})
                    continue

                existing_item, existing_score, sources = existing
                sources.add(source_name)
                merged_score = existing_score + score
                better_item = (
                    candidate
                    if len(candidate.snippet or "") > len(existing_item.snippet or "")
                    else existing_item
                )
                fused[key] = (replace(better_item, score=merged_score, source=self.name), merged_score, sources)

        _add(vector_results, source_name="vector", weight=1.25)
        _add(section_results, source_name="section", weight=0.85)

        ranked = sorted(
            (item for item, _score, _sources in fused.values()),
            key=lambda item: (
                -float(item.score or 0.0),
                0 if item.url.startswith("local://chunk/") else 1,
                item.title.lower().strip(),
            ),
        )
        return ranked[:max_results]


__all__ = ["LocalRAGRetriever"]
