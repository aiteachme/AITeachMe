from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib import cover as cover_module
from app.workflows.digest.docgen.lib import publish as publish_module


COURSE_ID = "course_publish00001"
USER_ID = "user-publish"


class _RecordingStore:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = dict(payloads)
        self.events: list[tuple[str, str]] = []

    async def write_text(self, key: str, value: str) -> None:
        self.events.append(("write", key))
        self.payloads[key] = value

    async def write_json_raw(self, key: str, value: object) -> None:
        self.events.append(("write", key))
        self.payloads[key] = value

    async def list_prefix(self, prefix: str) -> list[str]:
        self.events.append(("list", prefix))
        return sorted(key for key in self.payloads if key.startswith(prefix))

    async def delete(self, key: str) -> None:
        self.events.append(("delete", key))
        self.payloads.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        self.events.append(("delete_prefix", prefix))
        keys = [key for key in self.payloads if key.startswith(prefix)]
        for key in keys:
            self.payloads.pop(key, None)
        return len(keys)


class _FakeSession:
    def add(self, _value: object) -> None:
        return None

    def flush(self) -> None:
        return None


def _run_store_sync(func, *args, default=None, **kwargs):
    del default
    return asyncio.run(func(*args, **kwargs))


def _publish_kwargs(scope) -> dict[str, object]:
    return {
        "course_id": COURSE_ID,
        "build_group_id": "group-publish",
        "publish_token": "publish-token",
        "chapter_metadatas": [
            {
                "chapter_index": 1,
                "title": "矩阵",
                "markdown": "# 矩阵\n\n正文",
            }
        ],
        "chapter_assignments": [],
        "document_context": {"digest_mode": "systematic"},
        "cover_markdown": None,
        "user_prompt": "build",
        "requested_at": datetime.now(timezone.utc),
        "docgen_artifacts": {"build_metadata": {}},
        "course_scope": scope,
    }


def _patch_publish_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: _RecordingStore,
    transaction_context,
) -> None:
    fake_session = _FakeSession()

    @contextmanager
    def read_session():
        yield fake_session

    monkeypatch.setattr(publish_module, "get_content_store", lambda: store)
    monkeypatch.setattr(publish_module, "run_store_sync", _run_store_sync)
    monkeypatch.setattr(publish_module, "managed_session", read_session)
    monkeypatch.setattr(
        publish_module,
        "managed_knowledge_build_owner_transaction",
        transaction_context,
    )
    monkeypatch.setattr(publish_module.docgen_repo, "get_latest_version_no", lambda *_args: 0)
    monkeypatch.setattr(publish_module.docgen_repo, "get_docs_by_course", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        publish_module,
        "update_course_learning_context_from_docgen",
        lambda *args, **kwargs: None,
    )


def test_stage_failure_waits_for_thread_backed_sibling_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)

    async def run_scenario() -> None:
        sibling_started = threading.Event()
        release_sibling = threading.Event()
        sibling_finished = threading.Event()

        class _FailingStageStore:
            async def write_text(self, key: str, _value: str) -> None:
                if "chapter_02_" in key:
                    while not sibling_started.is_set():
                        await asyncio.sleep(0)
                    raise RuntimeError("staging write failed")

                def blocking_write() -> None:
                    sibling_started.set()
                    if not release_sibling.wait(timeout=2):
                        raise TimeoutError("test did not release sibling write")
                    sibling_finished.set()

                await asyncio.to_thread(blocking_write)

        monkeypatch.setattr(publish_module, "get_content_store", lambda: _FailingStageStore())

        stage_task = asyncio.create_task(
            publish_module.stage_knowledge_docs(
                course_id=COURSE_ID,
                chapter_metadatas=[
                    {"chapter_index": 1, "title": "矩阵", "markdown": "# 矩阵\n\n正文"},
                    {"chapter_index": 2, "title": "向量", "markdown": "# 向量\n\n正文"},
                ],
                course_scope=scope,
            )
        )
        while not sibling_started.is_set():
            await asyncio.sleep(0)

        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(stage_task), timeout=0.05)
        finally:
            release_sibling.set()

        with pytest.raises(RuntimeError, match="staging write failed"):
            await stage_task

        assert sibling_finished.is_set()

    asyncio.run(run_scenario())


def test_stage_cancellation_drains_merged_write_and_remaining_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)

    async def run_scenario() -> None:
        merged_started = threading.Event()
        release_merged = threading.Event()
        merged_finished = threading.Event()
        manifest_written = threading.Event()

        class _BlockingMergedStageStore:
            async def write_text(self, key: str, _value: str) -> None:
                if not key.endswith("merged_knowledge_base.md"):
                    return

                def blocking_write() -> None:
                    merged_started.set()
                    if not release_merged.wait(timeout=2):
                        raise TimeoutError("test did not release merged write")
                    merged_finished.set()

                await asyncio.to_thread(blocking_write)

            async def write_json_raw(self, _key: str, _value: object) -> None:
                manifest_written.set()

        monkeypatch.setattr(publish_module, "get_content_store", lambda: _BlockingMergedStageStore())
        monkeypatch.setattr(publish_module, "update_knowledge_build_status", lambda *_args, **_kwargs: None)

        stage_task = asyncio.create_task(
            publish_module.stage_knowledge_docs(
                course_id=COURSE_ID,
                chapter_metadatas=[
                    {"chapter_index": 1, "title": "矩阵", "markdown": "# 矩阵\n\n正文"},
                ],
                docgen_artifacts={"build_metadata": {}},
                course_scope=scope,
            )
        )
        while not merged_started.is_set():
            await asyncio.sleep(0)

        stage_task.cancel()
        await asyncio.sleep(0)
        stage_task.cancel()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(stage_task), timeout=0.05)
        finally:
            release_merged.set()

        with pytest.raises(asyncio.CancelledError):
            await stage_task

        assert merged_finished.is_set()
        assert manifest_written.is_set()

    asyncio.run(run_scenario())


def test_cancelled_cover_persistence_drains_without_mutating_published_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)

    async def run_scenario() -> None:
        write_started = threading.Event()
        release_write = threading.Event()
        write_finished = threading.Event()
        events: list[str] = []
        published_key = f"{scope.namespace}/assets/docgen/cover.published.png"

        class _BlockingCoverStore:
            def __init__(self) -> None:
                self.payloads: dict[str, object] = {published_key: b"published"}

            async def write_bytes(self, key: str, value: bytes) -> None:
                def blocking_write() -> None:
                    write_started.set()
                    if not release_write.wait(timeout=2):
                        raise TimeoutError("test did not release cover write")
                    write_finished.set()

                await asyncio.to_thread(blocking_write)
                self.payloads[key] = value
                events.append("write_finished")

            async def list_prefix(self, prefix: str) -> list[str]:
                raise AssertionError(f"cover generation must not scan published assets: {prefix}")

            async def delete(self, key: str) -> None:
                raise AssertionError(f"cover generation must not delete published assets: {key}")

            async def write_json_raw(self, key: str, value: object) -> None:
                events.append("sidecar")
                self.payloads[key] = value

        store = _BlockingCoverStore()
        settings = SimpleNamespace(
            docgen=SimpleNamespace(generate_cover_image=True),
            image_generation_enabled=True,
            models=SimpleNamespace(image_generation="test-image-model"),
        )
        model_policy = SimpleNamespace(
            model="test-image-model",
            timeout_s=1,
            max_retries=0,
            metadata=lambda: {},
        )

        async def fake_generate_image(*_args, **_kwargs):
            return SimpleNamespace(images=[SimpleNamespace(revised_prompt="")])

        async def fake_image_bytes(_image) -> tuple[bytes, str]:
            return b"new-cover", "image/png"

        monkeypatch.setattr(cover_module, "get_settings", lambda: settings)
        monkeypatch.setattr(cover_module, "get_docgen_model_policy", lambda *_args: model_policy)
        monkeypatch.setattr(
            cover_module,
            "_cover_size_candidates",
            lambda *_args, **_kwargs: ("1024x1024",),
        )
        monkeypatch.setattr(cover_module, "agenerate_image", fake_generate_image)
        monkeypatch.setattr(cover_module, "_image_bytes", fake_image_bytes)
        monkeypatch.setattr(cover_module, "get_content_store", lambda: store)
        monkeypatch.setattr(cover_module, "resolve_course_storage_scope", lambda _course_id: scope)
        monkeypatch.setattr(
            cover_module,
            "append_knowledge_build_recent_event",
            lambda *_args, **_kwargs: None,
        )

        cover_task = asyncio.create_task(
            cover_module.generate_docgen_cover_artifact(
                course_id=COURSE_ID,
                course_name="线性代数",
                build_session_id="build-cover",
                user_prompt=None,
                plan=None,
                digest_mode="systematic",
                confirmed_plan=None,
                requested_at=datetime.now(timezone.utc),
                build_group_id="group-cover",
            )
        )
        while not write_started.is_set():
            await asyncio.sleep(0)

        cover_task.cancel()
        await asyncio.sleep(0)
        cover_task.cancel()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(cover_task), timeout=0.05)
        finally:
            release_write.set()

        with pytest.raises(asyncio.CancelledError):
            await cover_task

        cover_prefix = f"{scope.namespace}/assets/docgen/"
        cover_keys = sorted(key for key in store.payloads if key.startswith(cover_prefix))
        generated_keys = [key for key in cover_keys if key != published_key]
        sidecar_key = scope.knowledge_build_prefix() + cover_module.DOCGEN_COVER_ARTIFACT_NAME
        assert write_finished.is_set()
        assert store.payloads[published_key] == b"published"
        assert len(generated_keys) == 1
        generated_key = generated_keys[0]
        assert generated_key.rsplit("/", 1)[-1].startswith("cover.")
        assert generated_key.endswith(".png")
        assert sidecar_key in store.payloads
        artifact = store.payloads[sidecar_key]
        assert isinstance(artifact, dict)
        assert artifact["storage_key"] == generated_key
        assert artifact["asset_path"] == f"../assets/docgen/{generated_key.rsplit('/', 1)[-1]}"
        assert events == ["write_finished", "sidecar"]

    asyncio.run(run_scenario())


def test_publish_commit_failure_keeps_old_live_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    old_chapter_key = scope.knowledge_doc_key("chapter_999_old.md")
    old_merged_key = scope.knowledge_doc_key("merged_knowledge_base.md")
    store = _RecordingStore(
        {
            old_chapter_key: "# 旧章节",
            old_merged_key: "# 旧合并文档",
        }
    )

    @contextmanager
    def failing_transaction(*_args, **_kwargs):
        yield _FakeSession()
        raise RuntimeError("injected_commit_failure")

    _patch_publish_dependencies(
        monkeypatch,
        store=store,
        transaction_context=failing_transaction,
    )

    with pytest.raises(RuntimeError, match="injected_commit_failure"):
        publish_module.publish_staged_knowledge_docs(**_publish_kwargs(scope))

    assert store.payloads[old_chapter_key] == "# 旧章节"
    assert store.payloads[old_merged_key] == "# 旧合并文档"
    written_keys = [key for event, key in store.events if event == "write"]
    assert written_keys
    assert all("/versions/v0001/" in key for key in written_keys)
    assert not any(event == "delete" for event, _key in store.events)


def test_publish_promotes_live_aliases_only_after_database_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    stale_key = scope.knowledge_doc_key("chapter_999_old.md")
    store = _RecordingStore({stale_key: "# 旧章节"})
    lifecycle_events: list[str] = []

    @contextmanager
    def committed_transaction(*_args, **_kwargs):
        lifecycle_events.append("transaction_enter")
        yield _FakeSession()
        lifecycle_events.append("database_commit")

    _patch_publish_dependencies(
        monkeypatch,
        store=store,
        transaction_context=committed_transaction,
    )
    monkeypatch.setattr(
        publish_module,
        "write_knowledge_manifest",
        lambda *args, **kwargs: lifecycle_events.append("manifest_ready") or "manifest.json",
    )

    original_write_text = store.write_text
    original_write_json_raw = store.write_json_raw
    original_delete = store.delete

    async def write_text(key: str, value: str) -> None:
        if "/versions/" not in key:
            lifecycle_events.append(f"live_write:{key}")
        await original_write_text(key, value)

    async def write_json_raw(key: str, value: object) -> None:
        if "/versions/" not in key:
            lifecycle_events.append(f"live_write:{key}")
        await original_write_json_raw(key, value)

    async def delete(key: str) -> None:
        lifecycle_events.append(f"stale_delete:{key}")
        await original_delete(key)

    store.write_text = write_text  # type: ignore[method-assign]
    store.write_json_raw = write_json_raw  # type: ignore[method-assign]
    store.delete = delete  # type: ignore[method-assign]

    publish_module.publish_staged_knowledge_docs(**_publish_kwargs(scope))

    commit_index = lifecycle_events.index("database_commit")
    live_write_indices = [
        index
        for index, event in enumerate(lifecycle_events)
        if event.startswith("live_write:")
    ]
    stale_delete_index = next(
        index
        for index, event in enumerate(lifecycle_events)
        if event.startswith("stale_delete:")
    )
    assert live_write_indices
    assert min(live_write_indices) > commit_index
    assert lifecycle_events.index("manifest_ready") > max(live_write_indices)
    assert stale_delete_index > lifecycle_events.index("manifest_ready")
    assert stale_key not in store.payloads
    assert "status_completed" not in lifecycle_events


def test_publish_live_projection_failure_keeps_committed_archive_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    stale_key = scope.knowledge_doc_key("chapter_999_old.md")
    store = _RecordingStore({stale_key: "# 旧章节"})
    lifecycle_events: list[str] = []

    @contextmanager
    def committed_transaction(*_args, **_kwargs):
        yield _FakeSession()
        lifecycle_events.append("database_commit")

    _patch_publish_dependencies(
        monkeypatch,
        store=store,
        transaction_context=committed_transaction,
    )
    monkeypatch.setattr(
        publish_module,
        "write_knowledge_manifest",
        lambda *args, **kwargs: lifecycle_events.append("manifest_ready") or "manifest.json",
    )
    monkeypatch.setattr(
        publish_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: lifecycle_events.append("status_completed"),
    )
    original_write_json_raw = store.write_json_raw

    async def fail_first_live_projection(key: str, value: object) -> None:
        if "/versions/" not in key:
            raise RuntimeError("live projection unavailable")
        await original_write_json_raw(key, value)

    store.write_json_raw = fail_first_live_projection  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="live projection unavailable"):
        publish_module.publish_staged_knowledge_docs(**_publish_kwargs(scope))

    assert lifecycle_events == ["database_commit"]
    assert store.payloads[stale_key] == "# 旧章节"
    versioned_writes = [
        key
        for event, key in store.events
        if event == "write" and "/versions/v0001/" in key
    ]
    assert versioned_writes
    assert not any(event == "delete" for event, _key in store.events)


def test_publish_uses_distinct_archive_prefixes_for_same_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    store = _RecordingStore({})

    @contextmanager
    def committed_transaction(*_args, **_kwargs):
        yield _FakeSession()

    _patch_publish_dependencies(
        monkeypatch,
        store=store,
        transaction_context=committed_transaction,
    )
    monkeypatch.setattr(publish_module, "write_knowledge_manifest", lambda *args, **kwargs: "manifest.json")
    monkeypatch.setattr(publish_module, "update_knowledge_build_status", lambda *args, **kwargs: None)

    first = _publish_kwargs(scope)
    first["publish_token"] = "publish-token-a"
    publish_module.publish_staged_knowledge_docs(**first)
    second = _publish_kwargs(scope)
    second["publish_token"] = "publish-token-b"
    publish_module.publish_staged_knowledge_docs(**second)

    archive_parents = {
        key.rsplit("/", 1)[0]
        for event, key in store.events
        if event == "write" and "/versions/v0001/" in key
    }
    assert len(archive_parents) == 2


def test_publish_revalidates_claim_before_live_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    old_chapter_key = scope.knowledge_doc_key("chapter_999_old.md")
    store = _RecordingStore({old_chapter_key: "# 旧章节"})
    transaction_calls: list[dict[str, object]] = []

    @contextmanager
    def transaction(*_args, **kwargs):
        transaction_calls.append(dict(kwargs))
        if len(transaction_calls) == 2:
            raise RuntimeError("knowledge_build_publish_claim_lost")
        yield _FakeSession()

    _patch_publish_dependencies(
        monkeypatch,
        store=store,
        transaction_context=transaction,
    )
    monkeypatch.setattr(
        publish_module,
        "write_knowledge_manifest",
        lambda *args, **kwargs: pytest.fail("lost owner must not publish a live manifest"),
    )

    with pytest.raises(RuntimeError, match="knowledge_build_publish_claim_lost"):
        publish_module.publish_staged_knowledge_docs(**_publish_kwargs(scope))

    assert len(transaction_calls) == 2
    assert transaction_calls[0].get("finish_publish", False) is False
    assert transaction_calls[1]["finish_publish"] is True
    assert store.payloads[old_chapter_key] == "# 旧章节"
    written_keys = [key for event, key in store.events if event == "write"]
    assert written_keys
    assert all("/versions/v0001/" in key for key in written_keys)


def test_publish_cleanup_preserves_runtime_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    runtime_key = scope.build_runtime_key()
    status_key = scope.build_status_key()
    staging_key = scope.knowledge_build_prefix() + "source_references.md"
    runtime_payload = {"docgen_runtime": {"status": "publishing"}}
    status_payload = {"status": "publishing"}
    store = _RecordingStore(
        {
            runtime_key: runtime_payload,
            status_key: status_payload,
            staging_key: "debug references",
        }
    )

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield _FakeSession()

    _patch_publish_dependencies(
        monkeypatch,
        store=store,
        transaction_context=transaction,
    )
    monkeypatch.setattr(
        publish_module,
        "write_knowledge_manifest",
        lambda *args, **kwargs: "manifest.json",
    )

    publish_module.publish_staged_knowledge_docs(**_publish_kwargs(scope))

    assert store.payloads[runtime_key] == runtime_payload
    assert store.payloads[status_key] == status_payload
    assert staging_key not in store.payloads
    assert not any(event == "delete_prefix" for event, _key in store.events)
