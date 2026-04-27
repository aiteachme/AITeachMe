from __future__ import annotations

from datetime import datetime, timezone

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


def test_load_current_published_markdown_prefers_live_merged_store(monkeypatch) -> None:
    subject_scope = build_subject_storage_scope(user_id="user_a", subject="linear-algebra")
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
        subject="linear-algebra",
        subject_scope=subject_scope,
        manifest=manifest,
    )

    assert markdown == "# 最新知识文档"
    assert updated_at == manifest.updated_at
