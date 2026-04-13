"""Source ranking and filtering helpers for retrieval-heavy workflows."""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.search.types import SearchResult

_TRUSTED_DOMAIN_KEYWORDS = (
    ".edu",
    ".gov",
    ".org",
    "wikipedia.org",
    "mathworld.wolfram.com",
    "ocw.mit.edu",
    "xuetangx.com",
    "icourse163.org",
    "zhihu.com",
    "csdn.net",
)

_BLACKLISTED_DOMAIN_MARKERS = (
    "baidu.com/zhidao",
    "360doc.com",
    "docin.com",
)


def _tokenize(text: str) -> list[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in normalized.split() if len(token) > 1]


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().strip()


class SourceCurator(BaseTracedExecution):
    async def execute(
        self,
        *,
        query: str,
        sources: list[SearchResult],
        max_results: int = 10,
    ) -> TracedExecutionResult:
        filtered = self._filter_sources(sources)
        ranked = self._rank_sources(query=query, sources=filtered)
        curated = ranked[:max_results]
        curated_domains = [_domain_from_url(item.url) for item in curated if not item.url.startswith("local://")]
        domain_counts = Counter(domain for domain in curated_domains if domain)
        trusted_source_count = sum(
            1 for item in curated if self._credibility_score(item.url, domain=_domain_from_url(item.url)) >= 0.8
        )
        local_source_count = sum(1 for item in curated if item.url.startswith("local://"))
        web_source_count = max(0, len(curated) - local_source_count)
        return TracedExecutionResult(
            metadata={
                "curated_sources": [item.to_dict() for item in curated],
                "candidate_count": len(sources),
                "filtered_count": len(filtered),
                "selected_count": len(curated),
                "trusted_source_count": trusted_source_count,
                "local_source_count": local_source_count,
                "web_source_count": web_source_count,
                "unique_domain_count": len(domain_counts),
                "top_domains": dict(domain_counts.most_common(5)),
            },
            sources=[item.url for item in curated if item.url],
        )

    async def curate_sources(
        self,
        *,
        query: str,
        sources: list[SearchResult],
        max_results: int = 10,
    ) -> tuple[list[SearchResult], dict[str, object]]:
        result = await self.run(query=query, sources=sources, max_results=max_results)
        curated = [
            SearchResult(
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
                score=float(item.get("score") or 0.0),
                source=str(item.get("source") or ""),
            )
            for item in result.metadata.get("curated_sources", [])
            if isinstance(item, dict)
        ]
        metadata = {key: value for key, value in result.metadata.items() if key != "curated_sources"}
        return curated, metadata

    def _filter_sources(self, sources: list[SearchResult]) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[str] = set()
        for item in sources:
            url = item.url.strip()
            key = url or f"{item.title.strip()}::{item.snippet.strip()[:120]}"
            if not key or key in seen:
                continue
            lowered = url.lower()
            if lowered and any(marker in lowered for marker in _BLACKLISTED_DOMAIN_MARKERS):
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _rank_sources(self, *, query: str, sources: list[SearchResult]) -> list[SearchResult]:
        query_tokens = Counter(_tokenize(query))

        def score(item: SearchResult) -> tuple[float, float, int, str]:
            domain = _domain_from_url(item.url)
            credibility = self._credibility_score(item.url, domain=domain)
            lexical = self._lexical_score(query_tokens, item)
            base_score = float(item.score or 0.0)
            total = (base_score * 0.35) + (lexical * 0.45) + (credibility * 0.2)
            if item.url.startswith("local://"):
                total += 0.8
            return (total, lexical, len(item.snippet or ""), item.title.lower().strip())

        return sorted(sources, key=score, reverse=True)

    def _credibility_score(self, url: str, *, domain: str) -> float:
        if url.startswith("local://"):
            return 1.0
        if not domain:
            return 0.0
        if any(keyword in domain for keyword in _TRUSTED_DOMAIN_KEYWORDS):
            return 0.85
        if domain.endswith(".com"):
            return 0.35
        return 0.5

    def _lexical_score(self, query_tokens: Counter[str], item: SearchResult) -> float:
        if not query_tokens:
            return 0.0
        text = f"{item.title} {item.snippet}"
        item_tokens = Counter(_tokenize(text))
        overlap = sum((query_tokens & item_tokens).values())
        return overlap / max(1, sum(query_tokens.values()))


__all__ = ["SourceCurator"]
