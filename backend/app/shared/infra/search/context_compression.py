"""Context compression helpers shared across retrieval-heavy workflows."""

from __future__ import annotations

import math
import re
from collections import Counter

from app.shared.infra.search.cache import get_compression_runtime_cache
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult

_FAST_PATH_CHAR_LIMIT = 2400
_DEFAULT_PASSAGE_MAX_CHARS = 900
_DEFAULT_MAX_TOTAL_CHARS = 4800


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _tokenize(text: str) -> list[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in normalized.split() if len(token) > 1]


def _lexical_overlap_score(query_tokens: Counter[str], passage: str) -> float:
    if not query_tokens:
        return 0.0
    passage_tokens = Counter(_tokenize(passage))
    if not passage_tokens:
        return 0.0
    overlap = sum((query_tokens & passage_tokens).values())
    return overlap / max(1, sum(query_tokens.values()))


def _normalize_for_dedupe(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _split_large_block(block: str, *, max_chars: int) -> list[str]:
    normalized = block.strip()
    if len(normalized) <= max_chars:
        return [normalized]

    sentences = [piece.strip() for piece in re.split(r"(?<=[。！？!?；;\.])\s+", normalized) if piece.strip()]
    if len(sentences) <= 1:
        return [normalized[index : index + max_chars].strip() for index in range(0, len(normalized), max_chars)]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        projected = current_len + len(sentence) + (1 if current else 0)
        if current and projected > max_chars:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_len = len(sentence)
            continue
        current.append(sentence)
        current_len = projected
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _document_to_passages(document: str, *, max_chars: int) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", document) if block.strip()]
    if not blocks:
        cleaned = document.strip()
        return [cleaned] if cleaned else []

    passages: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in blocks:
        for piece in _split_large_block(block, max_chars=max_chars):
            projected = current_len + len(piece) + (2 if current else 0)
            if current and projected > max_chars:
                passages.append("\n\n".join(current).strip())
                current = [piece]
                current_len = len(piece)
                continue
            current.append(piece)
            current_len = projected
    if current:
        passages.append("\n\n".join(current).strip())
    return [passage for passage in passages if passage]


def _dedupe_passages(passages: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: list[str] = []
    for passage in passages:
        normalized = _normalize_for_dedupe(passage)
        if not normalized:
            continue
        if normalized in seen:
            continue
        if any(
            min(len(normalized), len(existing)) > 160 and (normalized in existing or existing in normalized)
            for existing in seen
        ):
            continue
        seen.append(normalized)
        deduped.append(passage)
    return deduped


def _limit_by_total_chars(passages: list[str], *, max_total_chars: int) -> list[str]:
    selected: list[str] = []
    total = 0
    for passage in passages:
        if not passage.strip():
            continue
        projected = total + len(passage)
        if selected and projected > max_total_chars:
            break
        selected.append(passage)
        total = projected
    return selected or passages[:1]


def _build_compression_cache_payload(
    *,
    query: str,
    documents: list[str],
    focus_terms: list[str],
    similarity_threshold: float,
    lexical_threshold: float,
    max_results: int,
    max_total_chars: int,
    passage_max_chars: int,
) -> dict[str, object]:
    return {
        "query": str(query or "").strip(),
        "documents": [str(item or "") for item in documents],
        "focus_terms": [str(item or "").strip() for item in focus_terms if str(item or "").strip()],
        "similarity_threshold": float(similarity_threshold),
        "lexical_threshold": float(lexical_threshold),
        "max_results": int(max_results),
        "max_total_chars": int(max_total_chars),
        "passage_max_chars": int(passage_max_chars),
    }


class ContextCompressor(BaseTracedExecution):
    async def execute(
        self,
        *,
        query: str,
        documents: list[str],
        focus_terms: list[str] | None = None,
        similarity_threshold: float = 0.24,
        lexical_threshold: float = 0.12,
        max_results: int = 8,
        max_total_chars: int = _DEFAULT_MAX_TOTAL_CHARS,
        passage_max_chars: int = _DEFAULT_PASSAGE_MAX_CHARS,
    ) -> TracedExecutionResult:
        normalized_focus_terms = [str(item).strip() for item in focus_terms or [] if str(item).strip()]
        result, cache_status = await get_compression_runtime_cache().get_or_compute(
            payload=_build_compression_cache_payload(
                query=query,
                documents=documents,
                focus_terms=normalized_focus_terms,
                similarity_threshold=similarity_threshold,
                lexical_threshold=lexical_threshold,
                max_results=max_results,
                max_total_chars=max_total_chars,
                passage_max_chars=passage_max_chars,
            ),
            loader=lambda: self._execute_uncached(
                query=query,
                documents=documents,
                focus_terms=normalized_focus_terms,
                similarity_threshold=similarity_threshold,
                lexical_threshold=lexical_threshold,
                max_results=max_results,
                max_total_chars=max_total_chars,
                passage_max_chars=passage_max_chars,
            ),
        )
        result.metadata["cache_status"] = cache_status
        result.metadata["cache_hit"] = cache_status in {"hit", "shared"}
        return result

    async def _execute_uncached(
        self,
        *,
        query: str,
        documents: list[str],
        focus_terms: list[str],
        similarity_threshold: float,
        lexical_threshold: float,
        max_results: int,
        max_total_chars: int,
        passage_max_chars: int,
    ) -> TracedExecutionResult:
        cleaned_documents = [doc.strip() for doc in documents if str(doc).strip()]
        if not cleaned_documents:
            return TracedExecutionResult(metadata={"compression_mode": "empty"})

        passages = _dedupe_passages(
            [
                passage
                for document in cleaned_documents
                for passage in _document_to_passages(document, max_chars=passage_max_chars)
            ]
        )
        if not passages:
            return TracedExecutionResult(metadata={"compression_mode": "empty"})

        focus_query = " ".join([query.strip(), *focus_terms]).strip()
        query_tokens = Counter(_tokenize(focus_query))
        total_chars = sum(len(item) for item in passages)

        if total_chars <= _FAST_PATH_CHAR_LIMIT:
            ranked = sorted(
                passages,
                key=lambda item: (-_lexical_overlap_score(query_tokens, item), -len(item)),
            )
            selected = _limit_by_total_chars(ranked[:max_results], max_total_chars=max_total_chars)
            return TracedExecutionResult(
                content="\n\n".join(selected),
                metadata={
                    "compression_mode": "fast_path",
                    "document_count": len(cleaned_documents),
                    "passage_count": len(passages),
                    "selected_count": len(selected),
                    "focus_term_count": len(focus_terms),
                },
            )

        try:
            from app.shared.infra.embedding import aembed_texts

            embeddings = await aembed_texts([focus_query or query.strip() or "context", *passages])
            query_embedding = embeddings[0]
            scored: list[tuple[float, float, float, str]] = []
            for passage, embedding in zip(passages, embeddings[1:], strict=False):
                similarity = _cosine_similarity(query_embedding, embedding)
                lexical = _lexical_overlap_score(query_tokens, passage)
                if similarity >= similarity_threshold or lexical >= lexical_threshold:
                    score = similarity + (lexical * 0.35)
                    scored.append((score, similarity, lexical, passage))
            if scored:
                scored.sort(key=lambda item: (-item[0], -item[1], -item[2], -len(item[3])))
                ranked_passages = [passage for _, _, _, passage in scored[:max_results]]
                selected = _limit_by_total_chars(ranked_passages, max_total_chars=max_total_chars)
                return TracedExecutionResult(
                    content="\n\n".join(selected),
                    metadata={
                        "compression_mode": "embedding_filter",
                        "document_count": len(cleaned_documents),
                        "passage_count": len(passages),
                        "selected_count": len(selected),
                        "focus_term_count": len(focus_terms),
                    },
                )
        except Exception:
            pass

        ranked = sorted(
            passages,
            key=lambda item: (-_lexical_overlap_score(query_tokens, item), -len(item)),
        )
        selected = _limit_by_total_chars(ranked[:max_results], max_total_chars=max_total_chars)
        return TracedExecutionResult(
            content="\n\n".join(selected),
            metadata={
                "compression_mode": "lexical_fallback",
                "document_count": len(cleaned_documents),
                "passage_count": len(passages),
                "selected_count": len(selected),
                "focus_term_count": len(focus_terms),
            },
        )

    async def compress(
        self,
        query: str,
        documents: list[str],
        *,
        focus_terms: list[str] | None = None,
        similarity_threshold: float = 0.24,
        lexical_threshold: float = 0.12,
        max_results: int = 8,
        max_total_chars: int = _DEFAULT_MAX_TOTAL_CHARS,
        passage_max_chars: int = _DEFAULT_PASSAGE_MAX_CHARS,
    ) -> str:
        result = await self.run(
            query=query,
            documents=documents,
            focus_terms=focus_terms,
            similarity_threshold=similarity_threshold,
            lexical_threshold=lexical_threshold,
            max_results=max_results,
            max_total_chars=max_total_chars,
            passage_max_chars=passage_max_chars,
        )
        return result.content


ContextManager = ContextCompressor

__all__ = ["ContextCompressor", "ContextManager"]
