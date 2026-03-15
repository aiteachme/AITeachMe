"""
属性测试：Interact 引擎 — RAG 相关性（Property 8: RAG Relevance）

验证：
- len(results) <= k
- 结果按相似度降序排列（results[i].score >= results[i+1].score）
- 所有块属于查询的学科

策略：在内存 SQLite 中插入多学科的 Chunk + embedding 数据，
直接调用 vector_search 验证返回结果的不变量。
"""

import math
import hashlib
import os

import pytest
import sqlite_vec
import sqlalchemy as sa
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlmodel import SQLModel, Session, create_engine

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.repositories.models import (
    RawFile, Knowledge, Chunk, ParseStatus, PipelineStage,
)
from app.repositories.knowledge_repo import (
    vector_search, bulk_create_chunks, bulk_insert_embeddings,
)

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

EMBEDDING_DIM = 1536


def _deterministic_embedding(text: str) -> list[float]:
    """Generate a deterministic unit vector from text via SHA-256."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = []
    for i in range(EMBEDDING_DIM):
        byte_idx = i % len(digest)
        raw.append((digest[byte_idx] + i) % 256 / 255.0 - 0.5)
    norm = math.sqrt(sum(x * x for x in raw))
    if norm > 0:
        raw = [x / norm for x in raw]
    return raw


def _make_engine():
    """Create a fresh in-memory SQLite engine with sqlite-vec."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}
    )

    @sa.event.listens_for(eng, "connect")
    def _load_vec(dbapi_conn, connection_record):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    SQLModel.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
            f"USING vec0(chunk_id INTEGER PRIMARY KEY, "
            f"embedding FLOAT[{EMBEDDING_DIM}])"
        ))
        conn.commit()
    return eng


def _seed_subject(
    session: Session,
    subject: str,
    chunk_texts: list[str],
) -> list[Chunk]:
    """Insert RawFile → Knowledge → Chunks + embeddings for one subject."""
    raw = RawFile(
        subject=subject,
        filename=f"{subject}.pdf",
        filetype="pdf",
        file_path=f"data/raw/{subject}.pdf",
        parse_status=ParseStatus.PARSED,
    )
    session.add(raw)
    session.commit()
    session.refresh(raw)

    know = Knowledge(
        subject=subject,
        raw_file_id=raw.id,
        title=f"{subject} doc",
        markdown_content="# content",
        pipeline_stage=PipelineStage.EMBEDDED,
    )
    session.add(know)
    session.commit()
    session.refresh(know)

    chunks = [
        Chunk(
            knowledge_id=know.id,
            title=f"chunk-{i}",
            level=1,
            header_path=f"{subject} > chunk-{i}",
            chunk_index=i,
            content=t,
        )
        for i, t in enumerate(chunk_texts)
    ]
    chunks = bulk_create_chunks(session, chunks)
    bulk_insert_embeddings(
        session,
        [c.id for c in chunks],
        [_deterministic_embedding(t) for t in chunk_texts],
    )
    return chunks
