"""
属性测试：Digest 引擎 — 嵌入幂等性（Property 3: Embedding Idempotence）

验证：
- 相同文本嵌入两次的余弦相似度 > 0.9999

策略：mock litellm.aembedding，使其基于输入文本的哈希生成确定性向量，
从而验证 aembed_texts 对相同输入返回相同结果。
"""

import math
import hashlib
import os
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.core.embedding import aembed_texts

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

EMBEDDING_DIM = 1536


def _deterministic_vector(text: str) -> list[float]:
    """Generate a deterministic unit-ish vector from text via SHA-256."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand hash to fill EMBEDDING_DIM floats
    raw = []
    for i in range(EMBEDDING_DIM):
        byte_idx = i % len(digest)
        raw.append((digest[byte_idx] + i) % 256 / 255.0 - 0.5)
    # Normalize
    norm = math.sqrt(sum(x * x for x in raw))
    if norm > 0:
        raw = [x / norm for x in raw]
    return raw


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _make_mock_aembedding():
    """Create a mock that returns deterministic embeddings based on input text."""
    async def mock_aembedding(**kwargs):
        texts = kwargs.get("input", [])
        data = [
            {"embedding": _deterministic_vector(t), "index": i, "object": "embedding"}
            for i, t in enumerate(texts)
        ]

        class FakeUsage:
            def model_dump(self):
                return {"prompt_tokens": len(texts) * 10, "total_tokens": len(texts) * 10}

        class FakeResponse:
            def __init__(self):
                self.data = data
                self.usage = FakeUsage()

        return FakeResponse()

    return mock_aembedding


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

_embedding_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="\x00"),
    min_size=1,
    max_size=200,
).map(str.strip).filter(lambda s: len(s) > 0)

_text_lists = st.lists(_embedding_text, min_size=1, max_size=5)


# ═══════════════════════════════════════════════════════════════
# Property 3: Embedding Idempotence
# ═══════════════════════════════════════════════════════════════

@given(texts=_text_lists)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_embedding_idempotence(texts: list[str]):
    """P3: Embedding the same texts twice yields cosine similarity > 0.9999 for each."""
    import asyncio

    mock_fn = _make_mock_aembedding()

    with patch("app.core.embedding.litellm.aembedding", side_effect=mock_fn):
        vectors_1 = asyncio.get_event_loop().run_until_complete(aembed_texts(texts))
        vectors_2 = asyncio.get_event_loop().run_until_complete(aembed_texts(texts))

    assert len(vectors_1) == len(texts)
    assert len(vectors_2) == len(texts)

    for i, (v1, v2) in enumerate(zip(vectors_1, vectors_2)):
        sim = _cosine_similarity(v1, v2)
        assert sim > 0.9999, (
            f"Cosine similarity for text[{i}] = {sim:.6f}, expected > 0.9999"
        )


@given(text=_embedding_text)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_single_text_embedding_idempotence(text: str):
    """P3: A single text embedded twice produces identical vectors (cosine sim > 0.9999)."""
    import asyncio

    mock_fn = _make_mock_aembedding()

    with patch("app.core.embedding.litellm.aembedding", side_effect=mock_fn):
        vecs_1 = asyncio.get_event_loop().run_until_complete(aembed_texts([text]))
        vecs_2 = asyncio.get_event_loop().run_until_complete(aembed_texts([text]))

    sim = _cosine_similarity(vecs_1[0], vecs_2[0])
    assert sim > 0.9999, f"Cosine similarity = {sim:.6f}, expected > 0.9999"


@given(texts=_text_lists)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_embedding_vector_dimensions(texts: list[str]):
    """P3 (auxiliary): Each embedding vector has the expected dimensionality."""
    import asyncio

    mock_fn = _make_mock_aembedding()

    with patch("app.core.embedding.litellm.aembedding", side_effect=mock_fn):
        vectors = asyncio.get_event_loop().run_until_complete(aembed_texts(texts))

    assert len(vectors) == len(texts)
    for i, vec in enumerate(vectors):
        assert len(vec) == EMBEDDING_DIM, (
            f"Vector[{i}] dim={len(vec)}, expected {EMBEDDING_DIM}"
        )


def test_embedding_empty_input():
    """P3 (edge case): Empty input list returns empty output without calling LLM."""
    import asyncio

    vectors = asyncio.get_event_loop().run_until_complete(aembed_texts([]))
    assert vectors == []
