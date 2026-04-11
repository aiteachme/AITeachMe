"""Local RAG retriever with a section-based fallback."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.shared.infra.search.knowledge import RetrievedChunk
from app.shared.infra.search.api import search_knowledge
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult


def _tokenize(text: str) -> list[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in normalized.split() if len(token) > 1]


class LocalRAGRetriever(BaseRetriever):
    aliases = ("rag",)

    def __init__(self, *, subject: str | None = None, local_sections: list[Any] | None = None) -> None:
        self.subject = (subject or "").strip()
        self.local_sections = list(local_sections or [])

    @property
    def name(self) -> str:
        return "local_rag"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        results: list[SearchResult] = []
        if self.subject:
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
