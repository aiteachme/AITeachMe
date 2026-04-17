"""Source ranking and filtering helpers for retrieval-heavy workflows."""

from __future__ import annotations

from collections import Counter
import re
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

_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NORMALIZE_RE = re.compile(r"[\W_]+", re.UNICODE)


def _normalize_text(text: str) -> str:
    return _NORMALIZE_RE.sub("", str(text or "").strip().lower())


def _build_cjk_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for run in _CJK_RUN_RE.findall(str(text or "")):
        normalized = run.strip()
        if len(normalized) < 2:
            continue
        if len(normalized) <= 8:
            tokens.append(normalized)
        max_n = min(4, len(normalized))
        for ngram_size in range(2, max_n + 1):
            for index in range(len(normalized) - ngram_size + 1):
                tokens.append(normalized[index : index + ngram_size])
    return tokens


def _tokenize(text: str) -> list[str]:
    normalized = str(text or "").strip().lower()
    return [
        token
        for token in [*_LATIN_TOKEN_RE.findall(normalized), *_build_cjk_tokens(normalized)]
        if len(token) > 1
    ]


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().strip()


class SourceCurator(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "检索后处理"

    @property
    def trace_name(self) -> str:
        return "筛选引用来源"

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

        def score(item: SearchResult) -> tuple[float, float, float, float, int, str]:
            domain = _domain_from_url(item.url)
            credibility = self._credibility_score(item.url, domain=domain)
            lexical = self._lexical_score(query_tokens, item)
            phrase = self._phrase_match_score(query, item)
            base_score = float(item.score or 0.0)
            total = (base_score * 0.2) + (lexical * 0.35) + (phrase * 0.3) + (credibility * 0.15)
            if item.url.startswith("local://"):
                total += 0.8
            return (total, phrase, lexical, credibility, len(item.snippet or ""), item.title.lower().strip())

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
        title_tokens = Counter(_tokenize(item.title))
        snippet_tokens = Counter(_tokenize(item.snippet))
        title_overlap = sum((query_tokens & title_tokens).values())
        snippet_overlap = sum((query_tokens & snippet_tokens).values())
        weighted_overlap = (title_overlap * 1.25) + (snippet_overlap * 0.75)
        return min(1.0, weighted_overlap / max(1.0, float(sum(query_tokens.values()))))

    def _phrase_match_score(self, query: str, item: SearchResult) -> float:
        normalized_query = _normalize_text(query)
        if len(normalized_query) < 2:
            return 0.0

        normalized_title = _normalize_text(item.title)
        normalized_snippet = _normalize_text(item.snippet)
        if normalized_query in normalized_title:
            return 1.0
        if normalized_query in normalized_snippet:
            return 0.85

        query_terms = list(dict.fromkeys(_tokenize(query)))
        if not query_terms:
            return 0.0
        title_hits = sum(1 for term in query_terms if term in normalized_title)
        snippet_hits = sum(1 for term in query_terms if term in normalized_snippet)
        weighted_hits = (title_hits * 1.2) + (snippet_hits * 0.8)
        return min(1.0, weighted_hits / max(1.0, float(len(query_terms))))


__all__ = ["SourceCurator"]
