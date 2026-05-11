from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.shared.infra.knowledge.build_store as build_store
from app.models import Course, User
from app.models.build_planner import ConfirmedBuildPlan
from app.models.knowledge_doc import KnowledgeDocument
from app.shared.infra.knowledge.build_store import KnowledgeDocsManifest
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib import build_lifecycle
from app.workflows.digest.docgen.lib.published_manifest import ensure_published_knowledge_manifest


class _FakeContentStore:
    def __init__(self, content: str) -> None:
        self.content = content

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        if key.endswith("knowledge_markdowns/merged_knowledge_base.md"):
            return self.content
        return default


class _FakeJsonContentStore:
    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}
        self.deleted_prefixes: list[str] = []

    async def read_json(self, key: str, model):
        raw = self.payloads.get(key)
        return model.model_validate_json(raw) if raw is not None else None

    async def write_json(self, key: str, model) -> None:
        self.payloads[key] = model.model_dump_json()

    async def delete(self, key: str) -> None:
        self.payloads.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        matching_keys = [key for key in self.payloads if key.startswith(prefix)]
        for key in matching_keys:
            self.payloads.pop(key, None)
        return len(matching_keys)


def test_load_current_published_markdown_prefers_live_merged_store(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=1,
    )

    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: _FakeContentStore("# 最新知识文档"))
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("database fallback should not run")),
    )

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_linearalg012",
        course_scope=course_scope,
        manifest=manifest,
    )

    assert markdown == "# 最新知识文档"
    assert updated_at == manifest.updated_at


def test_knowledge_manifest_is_written_outside_staging_prefix(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=1,
    )
    fake_store = _FakeJsonContentStore()
    monkeypatch.setattr(build_store, "get_content_store", lambda: fake_store)

    key = build_store.write_knowledge_manifest(
        "course_linearalg012",
        manifest,
        course_scope=course_scope,
    )

    assert key == course_scope.build_manifest_key()
    assert not key.startswith(course_scope.knowledge_build_prefix())
    assert build_store.read_knowledge_manifest("course_linearalg012", course_scope=course_scope) == manifest


def test_clear_docgen_staging_uses_passed_course_scope(monkeypatch, tmp_path) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    build_dir = tmp_path / course_scope.namespace / "knowledge_markdowns" / "_build"
    build_dir.mkdir(parents=True)
    (build_dir / "runtime.json").write_text("{}", encoding="utf-8")
    fake_store = _FakeJsonContentStore()
    monkeypatch.setattr(build_store, "get_content_store", lambda: fake_store)
    monkeypatch.setattr(build_store, "get_runtime_data_dir", lambda: tmp_path)

    build_store.clear_docgen_staging("course_linearalg012", course_scope=course_scope)

    assert fake_store.deleted_prefixes == [course_scope.knowledge_build_prefix()]
    assert not build_dir.exists()


def test_knowledge_manifest_read_migrates_staged_manifest(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=2,
        chapter_count=1,
    )
    fake_store = _FakeJsonContentStore()
    fake_store.payloads[f"{course_scope.knowledge_build_prefix()}manifest.json"] = manifest.model_dump_json()
    monkeypatch.setattr(build_store, "get_content_store", lambda: fake_store)

    assert build_store.read_knowledge_manifest("course_linearalg012", course_scope=course_scope) == manifest
    assert course_scope.build_manifest_key() in fake_store.payloads
    assert f"{course_scope.knowledge_build_prefix()}manifest.json" not in fake_store.payloads


def test_imported_knowledge_docs_rebuild_published_manifest(monkeypatch) -> None:
    fake_store = _FakeJsonContentStore()
    monkeypatch.setattr(build_store, "get_content_store", lambda: fake_store)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, KnowledgeDocument.__table__],
    )

    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="user_a", username="user_a"))
        session.add(Course(id="course_abc123def456", user_id="user_a", name="Imported"))
        session.add(
            KnowledgeDocument(
                course_id="course_abc123def456",
                chapter_index=1,
                order_index=1,
                title="第一章",
                markdown_content="# 第一章",
                content_markdown="# 第一章",
                source_file_ids='["file_new"]',
                version_no=4,
                document_role="chapter",
                is_current=True,
                status="published",
                published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        session.add(
            KnowledgeDocument(
                course_id="course_abc123def456",
                chapter_index=2,
                order_index=2,
                title="草稿章",
                markdown_content="# 草稿章",
                content_markdown="# 草稿章",
                source_file_ids='["draft_file"]',
                version_no=5,
                document_role="chapter",
                is_current=True,
                status="draft",
            )
        )
        session.commit()

        ensure_published_knowledge_manifest(
            session,
            course_id="course_abc123def456",
            course_scope=build_course_storage_scope(user_id="user_a", course_id="course_abc123def456"),
        )

    manifest = build_store.read_knowledge_manifest(
        "course_abc123def456",
        course_scope=build_course_storage_scope(user_id="user_a", course_id="course_abc123def456"),
    )
    assert manifest is not None
    assert manifest.version_no == 4
    assert manifest.chapter_count == 1
    assert manifest.chapter_titles == ["第一章"]
    assert manifest.source_file_ids == ["file_new"]


def test_confirmed_plan_payload_keeps_course_name_from_plan_json() -> None:
    plan = ConfirmedBuildPlan(
        id="plan_a",
        course_id="course_a",
        user_prompt="学习计算机网络",
        plan_json={"course_name": "计算机网络与安全基础"},
    )

    payload = build_lifecycle._build_confirmed_plan_payload(
        plan,
        fallback_course_name="兜底主题",
    )

    assert payload["course_name"] == "计算机网络与安全基础"


def test_confirmed_plan_payload_uses_fallback_course_name() -> None:
    plan = ConfirmedBuildPlan(
        id="plan_b",
        course_id="course_b",
        user_prompt="学习计算机网络",
        plan_json={},
    )

    payload = build_lifecycle._build_confirmed_plan_payload(
        plan,
        fallback_course_name="计算机网络",
    )

    assert payload["course_name"] == "计算机网络"
