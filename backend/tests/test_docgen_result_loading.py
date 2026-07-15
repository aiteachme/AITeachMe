from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.shared.infra.knowledge.build_store as build_store
from app.models import Course, User
from app.models.build_planner import ConfirmedBuildPlan
from app.models.knowledge_doc import KnowledgeDocument
from app.shared.infra.knowledge.build_store import KnowledgeDocsManifest
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib.asset_requests import build_asset_request_block
from app.workflows.digest.docgen.lib import build_lifecycle
from app.workflows.digest.docgen.lib.published_manifest import (
    ensure_published_knowledge_manifest,
    select_published_knowledge_manifest,
)


class _FakeContentStore:
    def __init__(self, content: str) -> None:
        self.content = content

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        if key.endswith("knowledge_markdowns/merged_knowledge_base.md"):
            return self.content
        return default


class _MappedContentStore:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = dict(payloads)
        self.read_keys: list[str] = []

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        self.read_keys.append(key)
        return self.payloads.get(key, default)


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


def test_load_current_published_markdown_prefers_committed_database_docs(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    db_updated_at = datetime(2026, 4, 29, tzinfo=timezone.utc)
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=1,
    )

    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: _FakeContentStore("# 旧 live 文档"))
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                title="已提交知识文档",
                markdown_content="# 已提交知识文档",
                content_markdown="",
                markdown_path=None,
                updated_at=db_updated_at,
                published_at=None,
                created_at=db_updated_at,
            )
        ],
    )

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_linearalg012",
        course_scope=course_scope,
        manifest=manifest,
    )

    assert markdown == "# 已提交知识文档"
    assert updated_at == db_updated_at


def test_load_current_published_markdown_uses_committed_versioned_merged_artifact(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    db_updated_at = datetime(2026, 4, 29, tzinfo=timezone.utc)
    chapter_path = (
        f"{course_scope.namespace}/knowledge_markdowns/versions/"
        "v0004/receipt123/chapter_01_矩阵.md"
    )
    merged_path = chapter_path.rsplit("/", 1)[0] + "/merged_knowledge_base.md"
    current_path = course_scope.knowledge_doc_key("merged_knowledge_base.md")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=1,
    )
    monkeypatch.setattr(
        build_lifecycle,
        "get_content_store",
        lambda: _MappedContentStore(
            {
                merged_path: "![](assets/cover.png)\n\n# 矩阵\n\n正文\n\n## 参考资料\n\n- 来源 A",
                current_path: "# 旧 live 文档",
            }
        ),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                title="矩阵",
                markdown_content="# 矩阵\n\n正文",
                content_markdown="",
                markdown_path=chapter_path,
                updated_at=db_updated_at,
                published_at=None,
                created_at=db_updated_at,
            )
        ],
    )

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_linearalg012",
        course_scope=course_scope,
        manifest=manifest,
    )

    assert "![](assets/cover.png)" in markdown
    assert "## 参考资料" in markdown
    assert "旧 live 文档" not in markdown
    assert updated_at == db_updated_at


def test_load_current_published_markdown_rejects_foreign_versioned_artifact(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    db_updated_at = datetime(2026, 4, 29, tzinfo=timezone.utc)
    foreign_parent = (
        "users/user_b/courses/course_foreign123/"
        "knowledge_markdowns/versions/v0004/receipt123"
    )
    fake_store = _MappedContentStore(
        {
            f"{foreign_parent}/merged_knowledge_base.md": "# 其他课程文档",
            course_scope.knowledge_doc_key("merged_knowledge_base.md"): "# 旧 live 文档",
        }
    )
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: fake_store)
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                title="已提交知识文档",
                markdown_content="# 已提交知识文档",
                content_markdown="",
                markdown_path=f"{foreign_parent}/chapter_01.md",
                updated_at=db_updated_at,
                published_at=None,
                created_at=db_updated_at,
            )
        ],
    )

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_linearalg012",
        course_scope=course_scope,
        manifest=KnowledgeDocsManifest(
            updated_at=db_updated_at,
            version_no=4,
            chapter_count=1,
        ),
    )

    assert markdown == "# 已提交知识文档"
    assert updated_at == db_updated_at
    assert fake_store.read_keys == []


def test_load_current_published_markdown_rejects_mixed_versioned_paths(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    db_updated_at = datetime(2026, 4, 29, tzinfo=timezone.utc)
    receipt_parent = (
        f"{course_scope.namespace}/knowledge_markdowns/versions/v0004/receipt123"
    )
    fake_store = _MappedContentStore(
        {
            f"{receipt_parent}/merged_knowledge_base.md": "# 不应读取的归档文档",
            course_scope.knowledge_doc_key("merged_knowledge_base.md"): "# 旧 live 文档",
        }
    )
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: fake_store)
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                title="第一章",
                markdown_content="",
                content_markdown="",
                markdown_path=f"{receipt_parent}/chapter_01.md",
                updated_at=db_updated_at,
                published_at=None,
                created_at=db_updated_at,
            ),
            SimpleNamespace(
                title="第二章",
                markdown_content="",
                content_markdown="",
                markdown_path=receipt_parent,
                updated_at=db_updated_at,
                published_at=None,
                created_at=db_updated_at,
            ),
        ],
    )

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_linearalg012",
        course_scope=course_scope,
        manifest=KnowledgeDocsManifest(
            updated_at=db_updated_at,
            version_no=4,
            chapter_count=2,
        ),
    )

    assert markdown == ""
    assert updated_at == db_updated_at
    assert fake_store.read_keys == []


def test_empty_database_publication_does_not_revive_stale_storage_projection(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, KnowledgeDocument.__table__],
    )
    stale_manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=1,
        chapter_titles=["旧章节"],
    )
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    with Session(engine) as session:
        assert (
            select_published_knowledge_manifest(
                session,
                course_id="course_linearalg012",
                course_scope=course_scope,
                stored_manifest=stale_manifest,
            )
            is None
        )

    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: _FakeContentStore("# 旧 live 文档"))
    monkeypatch.setattr(build_lifecycle, "get_current_published_docs", lambda *_args, **_kwargs: [])

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_linearalg012",
        course_scope=course_scope,
        manifest=stale_manifest,
    )

    assert markdown == ""
    assert updated_at is None


def test_publish_completion_falls_back_to_committed_database_receipt(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_linearalg012")
    monkeypatch.setattr(build_lifecycle, "read_knowledge_build_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr(build_lifecycle, "managed_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [SimpleNamespace(build_session_id="build-session-a")],
    )

    assert build_lifecycle._docgen_publish_completed_for_owner(
        course_id="course_linearalg012",
        build_group_id="group-a",
        build_session_id="build-session-a",
        course_scope=course_scope,
    )
    assert not build_lifecycle._docgen_publish_completed_for_owner(
        course_id="course_linearalg012",
        build_group_id="group-a",
        build_session_id="build-session-b",
        course_scope=course_scope,
    )


def test_load_current_published_markdown_sanitizes_public_output(monkeypatch) -> None:
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_python012345")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=2,
        chapter_titles=["变量与数据类型", "条件判断"],
    )
    raw_markdown = (
        "# 变量与数据类型\n\n"
        "正文。\n\n"
        f"{build_asset_request_block('mermaid', '变量与数据类型关系图')}\n\n"
        "# 保存用户姓名\n\n"
        "name = \"小明\"\n\n"
        "---\n\n"
        "# 条件判断\n\n"
        "正文。"
    )

    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: _FakeContentStore(raw_markdown))
    monkeypatch.setattr(
        build_lifecycle,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                title="变量与数据类型",
                markdown_content="",
                content_markdown="",
                markdown_path=None,
                updated_at=manifest.updated_at,
                published_at=None,
                created_at=manifest.updated_at,
            )
        ],
    )

    markdown, updated_at = build_lifecycle._load_current_published_markdown(
        object(),
        course_id="course_python012345",
        course_scope=course_scope,
        manifest=manifest,
    )

    assert updated_at == manifest.updated_at
    assert "ATM_DOCGEN_ASSET_REQUEST" not in markdown
    assert "atm-docgen-internal-asset-request" not in markdown
    assert "\n## 保存用户姓名" in markdown
    assert "\n# 保存用户姓名" not in markdown
    assert markdown.count("\n# 条件判断") == 1


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
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_abc123def456")
    build_store.write_knowledge_manifest(
        "course_abc123def456",
        KnowledgeDocsManifest(
            updated_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            version_no=4,
            source_file_ids=["file_old"],
            chapter_count=1,
            chapter_titles=["旧章节"],
        ),
        course_scope=course_scope,
    )
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
            course_scope=course_scope,
        )

    manifest = build_store.read_knowledge_manifest(
        "course_abc123def456",
        course_scope=course_scope,
    )
    assert manifest is not None
    assert manifest.version_no == 4
    assert manifest.chapter_count == 1
    assert manifest.chapter_titles == ["第一章"]
    assert manifest.source_file_ids == ["file_new"]


def test_committed_docs_override_stale_manifest_metadata() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, KnowledgeDocument.__table__],
    )
    archive_parent = (
        "users/user_a/courses/course_abc123def456/"
        "knowledge_markdowns/versions/v0004/token-hash"
    )
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_abc123def456")

    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="user_a", username="user_a"))
        session.add(Course(id="course_abc123def456", user_id="user_a", name="Imported"))
        session.add(
            KnowledgeDocument(
                course_id="course_abc123def456",
                chapter_index=1,
                order_index=1,
                title="新章节",
                markdown_content="# 新章节",
                markdown_path=f"{archive_parent}/chapter_001.md",
                source_file_ids='["file_new"]',
                version_no=4,
                build_session_id="build-new",
                document_role="chapter",
                is_current=True,
                status="published",
                published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        manifest = select_published_knowledge_manifest(
            session,
            course_id="course_abc123def456",
            course_scope=course_scope,
            stored_manifest=KnowledgeDocsManifest(
                updated_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
                version_no=4,
                source_file_ids=["file_old"],
                prompt="old prompt",
                chapter_count=1,
                chapter_titles=["旧章节"],
                docgen_manifest_key=(
                    "users/user_a/courses/course_abc123def456/"
                    "knowledge_markdowns/versions/v0004/old-token/docgen_manifest.json"
                ),
            ),
            prompt="new prompt",
            build_session_id="build-new",
        )

    assert manifest is not None
    assert manifest.version_no == 4
    assert manifest.source_file_ids == ["file_new"]
    assert manifest.prompt == "new prompt"
    assert manifest.chapter_titles == ["新章节"]
    assert manifest.docgen_manifest_key == f"{archive_parent}/docgen_manifest.json"


def test_committed_manifest_rejects_foreign_versioned_path() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, KnowledgeDocument.__table__],
    )
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_abc123def456")
    foreign_parent = (
        "users/user_b/courses/course_foreign123/"
        "knowledge_markdowns/versions/v0004/receipt123"
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
                markdown_path=f"{foreign_parent}/chapter_01.md",
                version_no=4,
                document_role="chapter",
                is_current=True,
                status="published",
                published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        manifest = select_published_knowledge_manifest(
            session,
            course_id="course_abc123def456",
            course_scope=course_scope,
            stored_manifest=KnowledgeDocsManifest(
                updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                version_no=4,
                chapter_count=1,
                chapter_titles=["第一章"],
                docgen_manifest_key=f"{foreign_parent}/docgen_manifest.json",
            ),
        )

    assert manifest is not None
    assert manifest.docgen_manifest_key is None


def test_committed_manifest_rejects_mixed_valid_and_malformed_versioned_paths() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, KnowledgeDocument.__table__],
    )
    course_scope = build_course_storage_scope(user_id="user_a", course_id="course_abc123def456")
    receipt_parent = (
        f"{course_scope.namespace}/knowledge_markdowns/versions/v0004/receipt123"
    )

    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="user_a", username="user_a"))
        session.add(Course(id="course_abc123def456", user_id="user_a", name="Imported"))
        session.add_all(
            [
                KnowledgeDocument(
                    course_id="course_abc123def456",
                    chapter_index=1,
                    order_index=1,
                    title="第一章",
                    markdown_content="# 第一章",
                    markdown_path=f"{receipt_parent}/chapter_01.md",
                    version_no=4,
                    document_role="chapter",
                    is_current=True,
                    status="published",
                    published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                ),
                KnowledgeDocument(
                    course_id="course_abc123def456",
                    chapter_index=2,
                    order_index=2,
                    title="第二章",
                    markdown_content="# 第二章",
                    markdown_path=receipt_parent,
                    version_no=4,
                    document_role="chapter",
                    is_current=True,
                    status="published",
                    published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

        manifest = select_published_knowledge_manifest(
            session,
            course_id="course_abc123def456",
            course_scope=course_scope,
            stored_manifest=None,
        )

    assert manifest is not None
    assert manifest.docgen_manifest_key is None


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
