from __future__ import annotations

from datetime import datetime, timezone

import app.shared.infra.knowledge.build_store as build_store
from app.models.build_planner import ConfirmedBuildPlan
from app.shared.infra.knowledge.build_store import KnowledgeDocsManifest
from app.shared.infra.storage import build_subject_storage_scope
from app.workflows.digest.docgen.lib import build_lifecycle


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

    async def read_json(self, key: str, model):
        raw = self.payloads.get(key)
        return model.model_validate_json(raw) if raw is not None else None

    async def write_json(self, key: str, model) -> None:
        self.payloads[key] = model.model_dump_json()

    async def delete(self, key: str) -> None:
        self.payloads.pop(key, None)


def test_load_current_published_markdown_prefers_live_merged_store(monkeypatch) -> None:
    subject_scope = build_subject_storage_scope(user_id="user_a", subject_id="subj_linearalg012")
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
        subject_id="subj_linearalg012",
        subject_scope=subject_scope,
        manifest=manifest,
    )

    assert markdown == "# 最新知识文档"
    assert updated_at == manifest.updated_at


def test_knowledge_manifest_is_written_outside_staging_prefix(monkeypatch) -> None:
    subject_scope = build_subject_storage_scope(user_id="user_a", subject_id="subj_linearalg012")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=3,
        chapter_count=1,
    )
    fake_store = _FakeJsonContentStore()
    monkeypatch.setattr(build_store, "get_content_store", lambda: fake_store)

    key = build_store.write_knowledge_manifest(
        "subj_linearalg012",
        manifest,
        subject_scope=subject_scope,
    )

    assert key == subject_scope.build_manifest_key()
    assert not key.startswith(subject_scope.knowledge_build_prefix())
    assert build_store.read_knowledge_manifest("subj_linearalg012", subject_scope=subject_scope) == manifest


def test_knowledge_manifest_read_migrates_staged_manifest(monkeypatch) -> None:
    subject_scope = build_subject_storage_scope(user_id="user_a", subject_id="subj_linearalg012")
    manifest = KnowledgeDocsManifest(
        updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        version_no=2,
        chapter_count=1,
    )
    fake_store = _FakeJsonContentStore()
    fake_store.payloads[f"{subject_scope.knowledge_build_prefix()}manifest.json"] = manifest.model_dump_json()
    monkeypatch.setattr(build_store, "get_content_store", lambda: fake_store)

    assert build_store.read_knowledge_manifest("subj_linearalg012", subject_scope=subject_scope) == manifest
    assert subject_scope.build_manifest_key() in fake_store.payloads
    assert f"{subject_scope.knowledge_build_prefix()}manifest.json" not in fake_store.payloads


def test_confirmed_plan_payload_keeps_subject_name_from_plan_json() -> None:
    plan = ConfirmedBuildPlan(
        id="plan_a",
        subject_id="subj_a",
        user_prompt="学习计算机网络",
        plan_json={"subject_name": "计算机网络与安全基础"},
    )

    payload = build_lifecycle._build_confirmed_plan_payload(
        plan,
        fallback_subject_name="兜底主题",
    )

    assert payload["subject_name"] == "计算机网络与安全基础"


def test_confirmed_plan_payload_uses_fallback_subject_name() -> None:
    plan = ConfirmedBuildPlan(
        id="plan_b",
        subject_id="subj_b",
        user_prompt="学习计算机网络",
        plan_json={},
    )

    payload = build_lifecycle._build_confirmed_plan_payload(
        plan,
        fallback_subject_name="计算机网络",
    )

    assert payload["subject_name"] == "计算机网络"
