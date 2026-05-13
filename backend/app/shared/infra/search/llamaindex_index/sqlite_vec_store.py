"""SQLite-vec backed local VectorStore for course chunk embeddings."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable, Sequence

from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores.types import (
    BasePydanticVectorStore,
    VectorStoreQuery,
    VectorStoreQueryResult,
)
import sqlalchemy as sa
import structlog

from app.shared.infra.database import get_engine, quote_sqlite_identifier
from app.shared.infra.exceptions import VectorExtensionUnavailableError

logger = structlog.get_logger(__name__)

_VECTOR_TABLE_PREFIX = "atm_vec_chunks_dim_"
_VECTOR_TABLE_RE = re.compile(rf"^{_VECTOR_TABLE_PREFIX}(\d+)$")


def _load_sqlite_vec(connection: sa.Connection) -> None:
    """Load sqlite-vec into the current DB-API connection."""

    try:
        import sqlite_vec
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Local LlamaIndex indexing requires `sqlite-vec`.") from exc

    raw_connection = getattr(connection.connection, "driver_connection", None)
    if raw_connection is None:
        raw_connection = getattr(connection.connection, "connection", None)
    if raw_connection is None:
        raise RuntimeError("Cannot access raw SQLite connection for sqlite-vec.")

    raw_connection.enable_load_extension(True)
    try:
        try:
            sqlite_vec.load(raw_connection)
        except (OSError, sqlite3.Error) as exc:
            raise VectorExtensionUnavailableError("无法加载 sqlite-vec 原生扩展，向量索引暂不可用。") from exc
    finally:
        raw_connection.enable_load_extension(False)


def _serialize_float32(vector: Sequence[float]) -> bytes:
    try:
        import sqlite_vec
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Local LlamaIndex indexing requires `sqlite-vec`.") from exc
    return sqlite_vec.serialize_float32([float(item) for item in vector])


def _table_name_for_dim(embedding_dim: int) -> str:
    normalized_dim = int(embedding_dim)
    if normalized_dim <= 0:
        raise ValueError("embedding_dim must be a positive integer.")
    return f"{_VECTOR_TABLE_PREFIX}{normalized_dim}"


def _chunk_id_from_node_id(node_id: str | int | None) -> int | None:
    try:
        return int(str(node_id))
    except (TypeError, ValueError):
        return None


def _list_vector_tables(connection: sa.Connection) -> list[str]:
    rows = connection.execute(
        sa.text(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name LIKE :prefix
            """
        ),
        {"prefix": f"{_VECTOR_TABLE_PREFIX}%"},
    ).scalars()
    return sorted(name for name in rows if _VECTOR_TABLE_RE.fullmatch(str(name)))


def _vector_table_exists(connection: sa.Connection, table_name: str) -> bool:
    if not _VECTOR_TABLE_RE.fullmatch(str(table_name)):
        return False
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _delete_chunk_ids(
    connection: sa.Connection,
    *,
    table_name: str,
    course_id: str,
    chunk_ids: Iterable[int],
) -> None:
    ids = sorted({int(chunk_id) for chunk_id in chunk_ids})
    if not ids:
        return
    params = {f"chunk_id_{index}": chunk_id for index, chunk_id in enumerate(ids)}
    placeholders = ", ".join(f":{name}" for name in params)
    quoted_table = quote_sqlite_identifier(table_name)
    connection.execute(
        sa.text(
            f"DELETE FROM {quoted_table} "
            f"WHERE course = :course AND chunk_id IN ({placeholders})"
        ),
        {"course": course_id, **params},
    )


class SQLiteVecVectorStore(BasePydanticVectorStore):
    """Minimal LlamaIndex VectorStore implementation backed by sqlite-vec."""

    stores_text: bool = False
    course_id: str
    embedding_dim: int | None = None

    @classmethod
    def class_name(cls) -> str:
        return "SQLiteVecVectorStore"

    @property
    def client(self) -> Any:
        return get_engine()

    def _ensure_table(self, connection: sa.Connection, embedding_dim: int) -> str:
        table_name = _table_name_for_dim(embedding_dim)
        quoted_table = quote_sqlite_identifier(table_name)
        connection.execute(
            sa.text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {quoted_table} USING vec0("
                "chunk_id integer primary key, "
                "course text partition key, "
                f"embedding float[{int(embedding_dim)}] distance_metric=cosine"
                ")"
            )
        )
        return table_name

    def add(self, nodes: Sequence[BaseNode], **kwargs: Any) -> list[str]:
        del kwargs
        normalized_course_id = self.course_id.strip()
        if not normalized_course_id or not nodes:
            return []

        node_payloads: list[tuple[int, str, list[float]]] = []
        embedding_dim: int | None = self.embedding_dim
        for node in nodes:
            chunk_id = _chunk_id_from_node_id(node.node_id)
            if chunk_id is None:
                continue
            node_course_id = str(node.metadata.get("course_id") or node.metadata.get("course") or normalized_course_id).strip()
            if node_course_id != normalized_course_id:
                raise ValueError(
                    f"Node {node.node_id} belongs to course_id {node_course_id!r}, "
                    f"expected {normalized_course_id!r}."
                )
            embedding = [float(item) for item in node.get_embedding()]
            if not embedding:
                raise ValueError(f"Node {node.node_id} is missing an embedding.")
            if embedding_dim is None:
                embedding_dim = len(embedding)
            elif int(embedding_dim) != len(embedding):
                raise ValueError(
                    "All SQLiteVecVectorStore embeddings must share the same dimension. "
                    f"Expected {embedding_dim}, got {len(embedding)}."
                )
            node_payloads.append((chunk_id, node.node_id, embedding))

        if embedding_dim is None or not node_payloads:
            return []

        ids = [node_id for _, node_id, _ in node_payloads]
        chunk_ids = [chunk_id for chunk_id, _, _ in node_payloads]
        with get_engine().begin() as connection:
            _load_sqlite_vec(connection)
            table_name = self._ensure_table(connection, int(embedding_dim))
            # Delete across all local vector tables first so model upgrades do
            # not leave stale chunk IDs in old dimension tables.
            for existing_table in _list_vector_tables(connection):
                _delete_chunk_ids(
                    connection,
                    table_name=existing_table,
                    course_id=normalized_course_id,
                    chunk_ids=chunk_ids,
                )
            quoted_table = quote_sqlite_identifier(table_name)
            insert_stmt = sa.text(
                f"INSERT INTO {quoted_table}(chunk_id, course, embedding) "
                "VALUES (:chunk_id, :course, :embedding)"
            )
            for chunk_id, _, embedding in node_payloads:
                connection.execute(
                    insert_stmt,
                    {
                        "chunk_id": chunk_id,
                        "course": normalized_course_id,
                        "embedding": _serialize_float32(embedding),
                    },
                )

        logger.info(
            "sqlite_vec_nodes_added",
            course_id=normalized_course_id,
            embedding_dim=int(embedding_dim),
            node_count=len(ids),
        )
        return ids

    def delete(self, ref_doc_id: str, **delete_kwargs: Any) -> None:
        del delete_kwargs
        self.delete_nodes(node_ids=[ref_doc_id])

    def delete_nodes(
        self,
        node_ids: list[str] | None = None,
        filters: Any | None = None,
        **delete_kwargs: Any,
    ) -> None:
        del filters, delete_kwargs
        normalized_course_id = self.course_id.strip()
        chunk_ids = [
            chunk_id
            for node_id in (node_ids or [])
            if (chunk_id := _chunk_id_from_node_id(node_id)) is not None
        ]
        if not normalized_course_id or not chunk_ids:
            return

        with get_engine().begin() as connection:
            _load_sqlite_vec(connection)
            for table_name in _list_vector_tables(connection):
                _delete_chunk_ids(
                    connection,
                    table_name=table_name,
                    course_id=normalized_course_id,
                    chunk_ids=chunk_ids,
                )

    def clear(self) -> None:
        normalized_course_id = self.course_id.strip()
        if not normalized_course_id:
            return

        with get_engine().begin() as connection:
            _load_sqlite_vec(connection)
            for table_name in _list_vector_tables(connection):
                connection.execute(
                    sa.text(
                        f"DELETE FROM {quote_sqlite_identifier(table_name)} "
                        "WHERE course = :course"
                    ),
                    {"course": normalized_course_id},
                )

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        del kwargs
        normalized_course_id = self.course_id.strip()
        query_embedding = list(query.query_embedding or [])
        top_k = int(query.similarity_top_k or 0)
        if not normalized_course_id or not query_embedding or top_k <= 0:
            return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])

        table_name = _table_name_for_dim(len(query_embedding))
        with get_engine().connect() as connection:
            _load_sqlite_vec(connection)
            if not _vector_table_exists(connection, table_name):
                return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])
            rows = connection.execute(
                sa.text(
                    f"SELECT chunk_id, distance "
                    f"FROM {quote_sqlite_identifier(table_name)} "
                    "WHERE embedding MATCH :embedding "
                    "AND k = :top_k "
                    "AND course = :course "
                    "ORDER BY distance"
                ),
                {
                    "embedding": _serialize_float32(query_embedding),
                    "top_k": top_k,
                    "course": normalized_course_id,
                },
            ).all()

        ids = [str(int(row[0])) for row in rows]
        similarities = [
            1.0 / (1.0 + max(float(row[1] or 0.0), 0.0))
            for row in rows
        ]
        return VectorStoreQueryResult(nodes=[], similarities=similarities, ids=ids)

    def course_has_rows(self) -> bool:
        normalized_course_id = self.course_id.strip()
        if not normalized_course_id:
            return False
        with get_engine().connect() as connection:
            _load_sqlite_vec(connection)
            for table_name in _list_vector_tables(connection):
                count = connection.execute(
                    sa.text(
                        f"SELECT COUNT(*) FROM {quote_sqlite_identifier(table_name)} "
                        "WHERE course = :course"
                    ),
                    {"course": normalized_course_id},
                ).scalar_one()
                if int(count or 0) > 0:
                    return True
        return False

    def count_node_ids(self, node_ids: Iterable[str]) -> int:
        normalized_course_id = self.course_id.strip()
        chunk_ids = [
            chunk_id
            for node_id in node_ids
            if (chunk_id := _chunk_id_from_node_id(node_id)) is not None
        ]
        if not normalized_course_id or not chunk_ids:
            return 0

        total = 0
        with get_engine().connect() as connection:
            _load_sqlite_vec(connection)
            for table_name in _list_vector_tables(connection):
                params = {
                    f"chunk_id_{index}": chunk_id
                    for index, chunk_id in enumerate(sorted(set(chunk_ids)))
                }
                placeholders = ", ".join(f":{name}" for name in params)
                count = connection.execute(
                    sa.text(
                        f"SELECT COUNT(*) FROM {quote_sqlite_identifier(table_name)} "
                        f"WHERE course = :course AND chunk_id IN ({placeholders})"
                    ),
                    {"course": normalized_course_id, **params},
                ).scalar_one()
                total += int(count or 0)
        return total

    def list_node_ids(self, node_ids: Iterable[str]) -> set[str]:
        normalized_course_id = self.course_id.strip()
        chunk_ids = {
            chunk_id
            for node_id in node_ids
            if (chunk_id := _chunk_id_from_node_id(node_id)) is not None
        }
        if not normalized_course_id or not chunk_ids:
            return set()

        found: set[str] = set()
        with get_engine().connect() as connection:
            _load_sqlite_vec(connection)
            params = {
                f"chunk_id_{index}": chunk_id
                for index, chunk_id in enumerate(sorted(chunk_ids))
            }
            placeholders = ", ".join(f":{name}" for name in params)
            for table_name in _list_vector_tables(connection):
                rows = connection.execute(
                    sa.text(
                        f"SELECT chunk_id FROM {quote_sqlite_identifier(table_name)} "
                        f"WHERE course = :course AND chunk_id IN ({placeholders})"
                    ),
                    {"course": normalized_course_id, **params},
                ).scalars()
                found.update(str(int(chunk_id)) for chunk_id in rows if chunk_id is not None)
        return found


__all__ = ["SQLiteVecVectorStore"]
