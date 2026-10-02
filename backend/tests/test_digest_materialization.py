from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Course, DigestStep, RawFile, RetrievalChunk
from app.shared.infra import database
from app.shared.infra.course import build_precheck, settings as course_settings, vectors
from app.shared.infra.search.llamaindex_index import manager, sqlite_vec_store
from app.workflows.digest.common import indexing, materialize
from app.workflows.digest.common.models import SectionPacket, SharedInputs, SourcePacket
from app.workflows.digest.docgen.nodes import sync_knowledge_graph


COURSE_ID = "course-materialization"


@pytest.fixture
def materialization_db(monkeypatch, tmp_path):
    # Separate real connections expose SQLite self-locks hidden by StaticPool.
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'materialization.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 1},
    )
    SQLModel.metadata.create_all(engine)
    state = SimpleNamespace(
        engine=engine, active_sessions=0, manifests={},
        runtime=vectors.RuntimeEmbeddingConfig(
            configured=True, available=True, embedding_model="test-embedding", embedding_dim=2,
        ),
    )

    @contextmanager
    def transaction():
        with Session(engine, expire_on_commit=False) as session:
            state.active_sessions += 1
            try:
                yield session
                session.commit()
            finally:
                state.active_sessions -= 1

    state.transaction = transaction
    monkeypatch.setattr(materialize, "managed_session", transaction)
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    monkeypatch.setattr(sqlite_vec_store, "get_engine", lambda: engine)
    for module in (manager, course_settings, vectors, build_precheck):
        monkeypatch.setattr(module, "is_cloud_mode", lambda: False)
    for module in (materialize, vectors, build_precheck):
        monkeypatch.setattr(module, "get_runtime_embedding_config", lambda: state.runtime)
    monkeypatch.setattr(materialize, "_load_chunk_manifest", lambda cid: state.manifests.get(cid))

    def write_manifest(cid, manifest):
        state.manifests[cid] = manifest.model_copy(deep=True)
        return "manifest.json"

    monkeypatch.setattr(materialize, "_write_chunk_manifest", write_manifest)
    with transaction() as session:
        session.add(Course(id=COURSE_ID, user_id="local", name="Materialization"))
    yield state
    engine.dispose()


def inputs(*, count=1, content="A source paragraph", file_id="source-1"):
    sections = [SectionPacket(
        digest_chunk_uid=hashlib.sha256(f"{file_id}:{i}:{content}".encode()).hexdigest(),
        source_file_id=file_id, source_filename=f"{file_id}.md", chunk_index=i,
        title=f"Section {i}", header_path=f"Section {i}", level=1,
        normalized_content=content, preview=content, char_count=len(content),
    ) for i in range(count)]
    source = SourcePacket(
        file_id=file_id, filename=f"{file_id}.md", filetype="markdown", markdown_path="",
        asset_dir="", normalized_content=content, char_count=len(content),
        has_formulas=False, has_tables=False, has_images=False,
    )
    return SharedInputs(source_documents=[source], material_sections=sections)


async def build(source, run_id):
    return await materialize.materialize_shared_inputs(
        course_id=COURSE_ID, shared_inputs=source, build_session_id=run_id,
    )


@pytest.mark.anyio
async def test_embedding_wait_releases_database_connections(materialization_db, monkeypatch):
    observed = []

    async def embed(texts, **kwargs):
        observed.append((materialization_db.active_sessions, materialization_db.engine.pool.checkedout()))
        await asyncio.sleep(0)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    result = await build(inputs(), "first")
    assert observed == [(0, 0)]
    assert manager.list_indexed_chunk_ids(COURSE_ID, result.chunk_ids) == set(result.chunk_ids)
    with materialization_db.transaction() as session:
        assert session.get(RawFile, "source-1").current_step == DigestStep.EMBEDDED.value


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [False, True])
async def test_missing_embeddings_do_not_report_embedded(materialization_db, monkeypatch, enabled):
    materialization_db.runtime = materialization_db.runtime.model_copy(update={"available": enabled})

    async def unavailable(*args, **kwargs):
        return []

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", unavailable)
    result = await build(inputs(), "no-embeddings")
    assert not manager.list_indexed_chunk_ids(COURSE_ID, result.chunk_ids)
    with materialization_db.transaction() as session:
        assert session.get(RawFile, "source-1").current_step == DigestStep.CHUNKED.value


@pytest.mark.anyio
async def test_old_embedding_cannot_overwrite_newer_run(materialization_db, monkeypatch):
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0

    async def embed(texts, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await release_first.wait()
            return [[1.0, 0.0] for _ in texts]
        return [[0.0, 1.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    old = asyncio.create_task(build(inputs(), "old"))
    try:
        await asyncio.wait_for(first_started.wait(), 5)
        newer = await build(inputs(), "new")
        release_first.set()
        with pytest.raises(RuntimeError, match="superseded"):
            await old
        assert materialization_db.manifests[COURSE_ID].build_session_id == "new"
        with materialization_db.engine.connect() as connection:
            sqlite_vec_store._load_sqlite_vec(connection)
            value = connection.execute(sa.text(
                "SELECT vec_to_json(embedding) FROM atm_vec_chunks_dim_2 WHERE chunk_id = :id"
            ), {"id": newer.chunk_ids[0]}).scalar_one()
            assert json.loads(value) == [0.0, 1.0]
    finally:
        release_first.set()
        await asyncio.gather(old, return_exceptions=True)


@pytest.mark.anyio
async def test_reused_chunks_avoid_per_chunk_refresh(materialization_db, monkeypatch, record_property):
    calls = 0

    async def embed(texts, **kwargs):
        nonlocal calls
        calls += 1
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    source = inputs(count=40)
    first = await build(source, "first")
    queries = []

    def record_query(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "retrieval_chunk" in statement:
            queries.append(statement)

    sa.event.listen(materialization_db.engine, "before_cursor_execute", record_query)
    second = await build(source, "second")
    assert second.chunk_ids == first.chunk_ids
    assert calls == 1
    assert len(queries) < 15, f"unchanged rebuild issued {len(queries)} chunk queries"
    record_property("chunk_select_count", len(queries))


@pytest.mark.anyio
async def test_blocking_materialization_runs_off_event_loop(materialization_db, monkeypatch):
    loop_thread = threading.get_ident()

    def load_manifest(course_id):
        assert threading.get_ident() != loop_thread
        return None

    monkeypatch.setattr(materialize, "_load_chunk_manifest", load_manifest)
    materialization_db.runtime = materialization_db.runtime.model_copy(update={"available": False})
    await build(inputs(), "worker")


@pytest.mark.anyio
async def test_changed_embedding_model_rejects_inflight_results(materialization_db, monkeypatch):
    async def embed(texts, **kwargs):
        materialization_db.runtime = materialization_db.runtime.model_copy(
            update={"embedding_model": "new-model"},
        )
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    with pytest.raises(RuntimeError, match="embedding configuration"):
        await build(inputs(), "old-model")
    with materialization_db.transaction() as session:
        chunks = session.exec(select(RetrievalChunk)).all()
        assert all(chunk.vector_ref is None for chunk in chunks)
        assert session.get(RawFile, "source-1").current_step == DigestStep.CHUNKED.value


@pytest.mark.anyio
async def test_cancelled_embedding_leaves_retriable_chunks(materialization_db, monkeypatch):
    started = asyncio.Event()

    async def wait_for_cancellation(texts, **kwargs):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", wait_for_cancellation)
    task = asyncio.create_task(build(inputs(), "cancelled"))
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert materialization_db.active_sessions == 0
        with materialization_db.transaction() as session:
            assert session.get(RawFile, "source-1").current_step == DigestStep.CHUNKED.value

        async def embed(texts, **kwargs):
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
        retried = await build(inputs(), "retry")
        assert manager.list_indexed_chunk_ids(COURSE_ID, retried.chunk_ids) == set(retried.chunk_ids)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_source_changed_during_embedding_is_not_marked_complete(materialization_db, monkeypatch):
    async def embed(texts, **kwargs):
        with materialization_db.transaction() as session:
            source = session.get(RawFile, "source-1")
            source.markdown_content = "Fresh parse result"
            session.add(source)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    with pytest.raises(RuntimeError, match="source material was superseded"):
        await build(inputs(), "stale-source")
    with materialization_db.transaction() as session:
        assert session.get(RawFile, "source-1").markdown_content == "Fresh parse result"
        assert session.get(RawFile, "source-1").current_step != DigestStep.EMBEDDED.value


@pytest.mark.anyio
async def test_stale_prepared_source_cannot_revert_new_parse(materialization_db, monkeypatch):
    materialization_db.runtime = materialization_db.runtime.model_copy(update={"available": False})
    await build(inputs(), "first")
    with materialization_db.transaction() as session:
        source = session.get(RawFile, "source-1")
        source.markdown_content = "Fresh parse result"
        session.add(source)
    with pytest.raises(RuntimeError, match="source material was superseded"):
        await build(inputs(), "stale-source")
    with materialization_db.transaction() as session:
        assert session.get(RawFile, "source-1").markdown_content == "Fresh parse result"


@pytest.mark.anyio
async def test_changed_source_replaces_vectors_without_sqlite_write_lock(materialization_db, monkeypatch):
    async def embed(texts, **kwargs):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    await build(inputs(count=3), "old")
    with materialization_db.transaction() as session:
        source = session.get(RawFile, "source-1")
        source.markdown_content = "Fresh parse result"
        session.add(source)
    result = await build(inputs(content="Fresh parse result"), "new")
    with materialization_db.transaction() as session:
        chunks = session.exec(select(RetrievalChunk)).all()
        assert len(chunks) == 1
        assert chunks[0].content == "Fresh parse result"
        assert chunks[0].build_session_id == "new"
    assert manager.list_indexed_chunk_ids(COURSE_ID, result.chunk_ids) == set(result.chunk_ids)


@pytest.mark.anyio
async def test_published_docs_can_update_their_internal_source(materialization_db, monkeypatch):
    async def embed(texts, **kwargs):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    first = await indexing.index_published_knowledge_docs_for_retrieval(
        course_id=COURSE_ID, markdown="# Old chapter\n\nOld explanation.", raise_errors=True,
    )
    latest_body = "# Revised chapter\n\nThe revised explanation."
    latest = await indexing.index_published_knowledge_docs_for_retrieval(
        course_id=COURSE_ID, markdown=latest_body, raise_errors=True,
    )
    assert first.source_file_ids == latest.source_file_ids
    with materialization_db.transaction() as session:
        assert session.get(RawFile, latest.source_file_ids[0]).markdown_content == latest_body
        assert session.get(RawFile, latest.source_file_ids[0]).current_step == DigestStep.EMBEDDED.value
    assert manager.list_indexed_chunk_ids(COURSE_ID, latest.chunk_ids) == set(latest.chunk_ids)


@pytest.mark.anyio
async def test_existing_course_index_does_not_skip_a_new_source(materialization_db, monkeypatch):
    async def embed(texts, **kwargs):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    monkeypatch.setattr(sync_knowledge_graph, "managed_session", materialization_db.transaction)
    await build(inputs(), "old-source")
    indexed = []

    async def index_file(**kwargs):
        indexed.extend(kwargs["file_ids"])
        return await build(inputs(file_id="new-source"), "new-source")

    monkeypatch.setattr(sync_knowledge_graph, "index_course_files_for_retrieval", index_file)
    result = await sync_knowledge_graph.ensure_course_vector_index(
        course_id=COURSE_ID, file_ids=["new-source"],
    )
    assert indexed == ["new-source"]
    assert result == ("rebuilt", 1)


@pytest.mark.anyio
async def test_disabling_vectors_during_index_write_is_not_undone(materialization_db, monkeypatch):
    loop = asyncio.get_running_loop()
    writing_vectors = asyncio.Event()
    disabling_vectors = asyncio.Event()
    release_write = threading.Event()
    original_add = sqlite_vec_store.SQLiteVecVectorStore.add

    def gated_add(self, nodes, **kwargs):
        loop.call_soon_threadsafe(writing_vectors.set)
        assert release_write.wait(5)
        return original_add(self, nodes, **kwargs)

    async def embed(texts, **kwargs):
        return [[1.0, 0.0] for _ in texts]

    def disable():
        with materialization_db.transaction() as session:
            course = session.get(Course, COURSE_ID)
            conflict = build_precheck.inspect_course_build_precheck(session, course=course)
            loop.call_soon_threadsafe(disabling_vectors.set)
            return build_precheck.resolve_course_build_vector_status(
                session, course=course, embedding_resolution="disable", prechecked_conflict=conflict,
            )

    monkeypatch.setattr(materialize, "aembed_texts_for_ingestion", embed)
    monkeypatch.setattr(sqlite_vec_store.SQLiteVecVectorStore, "add", gated_add)
    build_task = asyncio.create_task(build(inputs(), "writing"))
    disable_task = None
    try:
        await asyncio.wait_for(writing_vectors.wait(), 5)
        disable_task = asyncio.create_task(asyncio.to_thread(disable))
        await asyncio.wait_for(disabling_vectors.wait(), 5)
        # The configuration mutation should queue behind the short write scope.
        # The broken implementation completes it before the older write finishes.
        try:
            await asyncio.wait_for(asyncio.shield(disable_task), 0.15)
        except TimeoutError:
            pass
        release_write.set()
        await build_task
        assert (await disable_task).mode == "disabled"
        with materialization_db.transaction() as session:
            binding = course_settings.get_course_embedding_binding(session.get(Course, COURSE_ID))
            assert binding.mode.value == "disabled"
    finally:
        release_write.set()
        tasks = [build_task] + ([disable_task] if disable_task is not None else [])
        await asyncio.gather(*tasks, return_exceptions=True)
