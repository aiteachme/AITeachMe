"""
Knowledge + KnowledgeGraphNode + Chunk CRUD 及向量检索
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlmodel import Session, select, func

from app.core.database import require_vec_ready
from app.repositories.models import (
    Knowledge,
    KnowledgeGraphNode,
    Chunk,
)


# ─── Knowledge CRUD ───


def create_knowledge(session: Session, knowledge: Knowledge) -> Knowledge:
    session.add(knowledge)
    session.commit()
    session.refresh(knowledge)
    return knowledge


def get_knowledge_by_id(session: Session, knowledge_id: int) -> Knowledge | None:
    return session.get(Knowledge, knowledge_id)


def get_knowledge_by_raw_file_id(session: Session, raw_file_id: int) -> Knowledge | None:
    stmt = select(Knowledge).where(Knowledge.raw_file_id == raw_file_id)
    return session.exec(stmt).first()


def update_pipeline_stage(
    session: Session, knowledge_id: int, stage: str
) -> Knowledge | None:
    knowledge = session.get(Knowledge, knowledge_id)
    if knowledge is None:
        return None
    knowledge.pipeline_stage = stage
    session.add(knowledge)
    session.commit()
    session.refresh(knowledge)
    return knowledge


def update_knowledge_content(
    session: Session, knowledge_id: int, markdown_content: str
) -> Knowledge | None:
    knowledge = session.get(Knowledge, knowledge_id)
    if knowledge is None:
        return None
    knowledge.markdown_content = markdown_content
    session.add(knowledge)
    session.commit()
    session.refresh(knowledge)
    return knowledge


def list_knowledge_by_subject(
    session: Session, subject: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[Knowledge], int]:
    count_stmt = select(func.count()).select_from(Knowledge).where(Knowledge.subject == subject)
    total = session.exec(count_stmt).one()

    stmt = (
        select(Knowledge)
        .where(Knowledge.subject == subject)
        .order_by(Knowledge.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    items = list(session.exec(stmt).all())
    return items, total


# ─── KnowledgeGraphNode CRUD ───


def create_graph_node(session: Session, node: KnowledgeGraphNode) -> KnowledgeGraphNode:
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def bulk_create_graph_nodes(
    session: Session, nodes: list[KnowledgeGraphNode]
) -> list[KnowledgeGraphNode]:
    for node in nodes:
        session.add(node)
    session.commit()
    for node in nodes:
        session.refresh(node)
    return nodes


def get_graph_nodes_by_knowledge_id(
    session: Session, knowledge_id: int
) -> list[KnowledgeGraphNode]:
    """按 knowledge_id 获取所有节点（扁平列表，调用方负责构建树）。"""
    stmt = (
        select(KnowledgeGraphNode)
        .where(KnowledgeGraphNode.knowledge_id == knowledge_id)
        .order_by(KnowledgeGraphNode.order_index)
    )
    return list(session.exec(stmt).all())


def list_graph_nodes_by_subject(
    session: Session, subject: str
) -> list[KnowledgeGraphNode]:
    """按学科获取所有 KnowledgeGraphNode（通过 JOIN Knowledge 过滤）。"""
    stmt = (
        select(KnowledgeGraphNode)
        .join(Knowledge, KnowledgeGraphNode.knowledge_id == Knowledge.id)
        .where(Knowledge.subject == subject)
        .order_by(KnowledgeGraphNode.knowledge_id, KnowledgeGraphNode.order_index)
    )
    return list(session.exec(stmt).all())


# ─── Chunk CRUD ───


def bulk_create_chunks(session: Session, chunks: list[Chunk]) -> list[Chunk]:
    for chunk in chunks:
        session.add(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


def get_chunks_by_knowledge_id(session: Session, knowledge_id: int) -> list[Chunk]:
    stmt = (
        select(Chunk)
        .where(Chunk.knowledge_id == knowledge_id)
        .order_by(Chunk.chunk_index)
    )
    return list(session.exec(stmt).all())


def bulk_insert_embeddings(
    session: Session, chunk_ids: list[int], embeddings: list[list[float]]
) -> None:
    """批量插入 embedding 到 chunk_embeddings vec0 虚拟表。"""
    require_vec_ready()
    conn = session.connection()
    for chunk_id, embedding in zip(chunk_ids, embeddings):
        conn.execute(
            sa.text(
                "INSERT INTO chunk_embeddings(chunk_id, embedding) VALUES (:cid, :emb)"
            ),
            {"cid": chunk_id, "emb": str(embedding)},
        )
    session.commit()


# ─── 向量相似度搜索 ───


@dataclass
class ChunkSearchResult:
    chunk: Chunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    """
    向量相似度搜索，支持学科过滤和 top_k，返回相似度分数。

    通过 JOIN chunk → knowledge 实现学科过滤。
    结果按相似度降序排列（distance 越小越相似）。
    """
    require_vec_ready()
    conn = session.connection()

    # sqlite-vec 返回 distance（越小越相似），转换为 similarity score
    sql = sa.text("""
        SELECT
            ce.chunk_id,
            ce.distance
        FROM chunk_embeddings ce
        JOIN chunk c ON c.id = ce.chunk_id
        JOIN knowledge k ON k.id = c.knowledge_id
        WHERE k.subject = :subject
          AND ce.embedding MATCH :query_emb
        ORDER BY ce.distance
        LIMIT :top_k
    """)

    rows = conn.execute(
        sql,
        {"subject": subject, "query_emb": str(query_embedding), "top_k": top_k},
    ).fetchall()

    results: list[ChunkSearchResult] = []
    for row in rows:
        chunk_id, distance = row[0], row[1]
        chunk = session.get(Chunk, chunk_id)
        if chunk is not None:
            # 将 distance 转换为 similarity score（1 - distance 或 1/(1+distance)）
            score = 1.0 / (1.0 + distance) if distance >= 0 else 0.0
            results.append(ChunkSearchResult(chunk=chunk, score=score))

    return results
