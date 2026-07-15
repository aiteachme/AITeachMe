from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.knowledge import CourseVectorStatusResponse, DocGenGetResponse
from app.shared.infra.knowledge.build_store import KnowledgeDocsManifest
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib import build_lifecycle
from app.workflows.digest.docgen.lib import published_chunks


COURSE_ID = "course_chunktest001"


def _snapshot(publication_id: str, *, version_no: int = 4):
    return published_chunks._PublicationSnapshot(
        publication_id=publication_id,
        version_no=version_no,
        updated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        chapters=(
            published_chunks._PublishedChapter(chapter_index=1, title="第一章"),
            published_chunks._PublishedChapter(chapter_index=2, title="第二章"),
        ),
    )


def test_published_chunks_preserve_authoritative_markdown_and_outer_material() -> None:
    markdown = (
        "## 课程封面\n\n导读。\n\n"
        "# 第一章\n\n正文一。\n\n## 小结\n\nA\n\n"
        "# 第二章\n\n正文二。\n\n## 小结\n\nB\n\n"
        "## 参考资料\n\n- ref\n"
    )

    chunks = published_chunks._split_published_markdown(
        markdown,
        chapters=_snapshot("v0004-preserve").chapters,
    )

    assert "".join(chunk.markdown for chunk in chunks) == markdown
    assert chunks[0].markdown.startswith("## 课程封面")
    assert chunks[-1].markdown.endswith("## 参考资料\n\n- ref\n")
    assert sum(len(chunk.markdown) for chunk in chunks) == len(markdown)


def test_published_heading_ids_match_frontend_global_slug_contract() -> None:
    markdown = (
        "# 第一章\n\n"
        "## 小结\n\n"
        "> ## 小结\n\n"
        "```md\n# 小结\n```\n\n"
        "## API_2 / α 与 中文！\n\n"
        "# 第二章\n\n"
        "## 小结\n"
    )

    chunks = published_chunks._split_published_markdown(
        markdown,
        chapters=_snapshot("v0004-headings").chapters,
    )
    headings = [heading for chunk in chunks for heading in chunk.headings]

    assert [heading.id for heading in headings] == [
        "第一章",
        "小结",
        "api_2-与-中文",
        "第二章",
        "小结-2",
    ]
    assert [heading.chunk_index for heading in headings] == [0, 0, 0, 1, 1]


def test_published_headings_match_frontend_display_cleanup_contract() -> None:
    markdown = (
        "# 第一章 {#ku_chapter_one}\n\n"
        "## 图 ![不会进入 ID](asset.png) 标题 <!-- ATM_KU: ku_image -->\n\n"
        "# 第二章 <!-- ATM_KU: ku_chapter_two -->\n\n"
        "## API_2 ![ALT](asset.png) / α 与 中文！ {#ku_topic}\n"
    )

    chunks = published_chunks._split_published_markdown(
        markdown,
        chapters=_snapshot("v0004-display-cleanup").chapters,
    )
    headings = [heading for chunk in chunks for heading in chunk.headings]

    assert [heading.text for heading in headings] == [
        "第一章",
        "图  标题",
        "第二章",
        "API_2  / α 与 中文！",
    ]
    assert [heading.id for heading in headings] == [
        "第一章",
        "图-标题",
        "第二章",
        "api_2-与-中文",
    ]


def test_chunk_request_rejects_publication_switch_during_markdown_read(monkeypatch) -> None:
    old_snapshot = _snapshot("v0004-old")
    new_snapshot = _snapshot("v0005-new", version_no=5)
    snapshots = iter([old_snapshot, new_snapshot])
    reads: list[str] = []
    monkeypatch.setattr(
        published_chunks,
        "_load_publication_snapshot",
        lambda **_kwargs: next(snapshots),
    )
    monkeypatch.setattr(
        published_chunks,
        "get_docgen_result",
        lambda **_kwargs: reads.append("markdown")
        or DocGenGetResponse(
            exists=True,
            markdown="# 第一章\n\n旧正文\n\n# 第二章\n\n旧正文二",
        ),
    )
    with published_chunks._PUBLICATION_CACHE_LOCK:
        published_chunks._PUBLICATION_CACHE.clear()

    with pytest.raises(published_chunks.PublishedDocumentStaleError):
        published_chunks.get_published_doc_chunk(
            course_id=COURSE_ID,
            course_scope=build_course_storage_scope(user_id="user-a", course_id=COURSE_ID),
            publication_id=old_snapshot.publication_id,
            chunk_index=0,
        )

    assert reads == ["markdown"]
    with published_chunks._PUBLICATION_CACHE_LOCK:
        assert old_snapshot.publication_id not in published_chunks._PUBLICATION_CACHE


def test_chunk_request_rejects_stale_id_before_reading_markdown(monkeypatch) -> None:
    current = _snapshot("v0005-current", version_no=5)
    monkeypatch.setattr(
        published_chunks,
        "_load_publication_snapshot",
        lambda **_kwargs: current,
    )
    monkeypatch.setattr(
        published_chunks,
        "get_docgen_result",
        lambda **_kwargs: pytest.fail("stale publication must not read Markdown"),
    )

    with pytest.raises(published_chunks.PublishedDocumentStaleError):
        published_chunks.get_published_doc_chunk(
            course_id=COURSE_ID,
            course_scope=build_course_storage_scope(user_id="user-a", course_id=COURSE_ID),
            publication_id="v0004-stale",
            chunk_index=0,
        )


def test_docgen_metadata_query_skips_published_and_draft_body_reads(monkeypatch) -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    scope = build_course_storage_scope(user_id="user-a", course_id=COURSE_ID)
    manifest = KnowledgeDocsManifest(
        updated_at=now,
        version_no=4,
        source_file_ids=["file-a"],
        chapter_count=2,
        chapter_titles=["第一章", "第二章"],
    )
    monkeypatch.setattr(build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        build_lifecycle,
        "_resolve_current_published_manifest",
        lambda *args, **kwargs: manifest,
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_load_current_published_markdown",
        lambda *args, **kwargs: pytest.fail("published body must not be read"),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "get_content_store",
        lambda: pytest.fail("draft store must not be opened"),
    )
    monkeypatch.setattr(build_lifecycle, "_resolve_runtime_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(build_lifecycle, "_build_runtime_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        build_lifecycle,
        "get_course_vector_status_by_id",
        lambda *args, **kwargs: CourseVectorStatusResponse(),
    )

    response = build_lifecycle.get_docgen_result(
        SimpleNamespace(),
        course_id=COURSE_ID,
        course_scope=scope,
        include_markdown=False,
        include_draft=False,
    )

    assert response.exists is True
    assert response.markdown == ""
    assert response.draft_markdown == ""
    assert response.updated_at == now
    assert response.source_file_ids == ["file-a"]
