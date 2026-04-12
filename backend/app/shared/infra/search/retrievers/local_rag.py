"""Local RAG retriever with a section-based fallback."""

from __future__ import annotations

from collections import Counter
from typing import Any
import re
import structlog

from app.shared.infra.search.knowledge import RetrievedChunk
from app.shared.infra.search.api import get_knowledge_search_notice, search_knowledge
from app.shared.infra.search.retrievers.base import BaseRetriever
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

    def __init__(self, *, subject: str | None = None, local_sections: list[Any] | None = None) -> None:
        self.subject = (subject or "").strip()
        self.local_sections = list(local_sections or [])
        self._vector_search_available: bool | None = None
        self._vector_search_notice: str | None = None
        self._vector_notice_logged = False

    @property
    def name(self) -> str:
        return "local_rag"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        results: list[SearchResult] = []
        if self.local_sections:
            results.extend(self._section_fallback(query, max_results=max_results))
            if results:
                return results[:max_results]

        should_try_vector = bool(self.subject)
        if should_try_vector and self.local_sections:
            should_try_vector = await self._refresh_vector_search_availability()
        if should_try_vector and self.subject:
            try:
                vector_results = await search_knowledge(query, self.subject, top_k=max_results)
            except Exception:
                vector_results = []
            results.extend(self._from_chunks(vector_results))

        if len(results) >= max_results or not self.local_sections:
            return results[:max_results]

        seen_urls = {item.url for item in results}
        for item in self._section_fallback(query, max_results=max_results * 2):
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            results.append(item)
            if len(results) >= max_results:
                break
        return results[:max_results]

    async def _refresh_vector_search_availability(self) -> bool:
        if self._vector_search_available is not None:
            return self._vector_search_available

        notice = await get_knowledge_search_notice(self.subject)
        self._vector_search_notice = notice
        self._vector_search_available = notice is None
        if notice and not self._vector_notice_logged:
            logger.info(
                "local_rag_vector_search_bypassed",
                subject=self.subject,
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


__all__ = ["LocalRAGRetriever"]
