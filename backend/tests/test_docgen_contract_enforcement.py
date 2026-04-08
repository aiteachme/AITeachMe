from __future__ import annotations

import asyncio
import inspect
from contextlib import contextmanager
from datetime import datetime

from sqlmodel import select

from app.models.knowledge_doc import KnowledgeDoc
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.common.context import create_langgraph_dev_context
from app.workflows.digest.docgen.nodes.load_context_node import build_load_context_node
from app.workflows.digest.docgen.publish import publish_staged_knowledge_docs
from app.workflows.digest.observability import DigestTokenSummary, build_docgen_lane_summary
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SourcePacket, SubjectProfile


def _build_shared_inputs() -> SharedInputs:
    return SharedInputs(
        source_packets=[
            SourcePacket(
                file_id=1,
                filename="demo.md",
                filetype="markdown",
                markdown_path="demo.md",
                asset_dir="assets",
                normalized_content="偏导数、梯度和方向导数的概念整理。",
                char_count=120,
                has_formulas=True,
                has_tables=False,
                has_images=False,
            )
        ],
        fast_hints=FastTopicHints(chapter_candidates=["偏导数", "梯度", "方向导数"]),
        subject_profile=SubjectProfile(
            subject_name="高等数学",
            discipline="数学",
            sub_discipline="多元微积分",
            key_topics=["偏导数", "梯度", "方向导数"],
            has_heavy_formulas=True,
        ),
    )


def test_load_context_requires_confirmed_plan() -> None:
    node = build_load_context_node(context=create_langgraph_dev_context("digest.docgen.contract"))
    result = asyncio.run(
        node(
            {
                "subject": "demo",
                "requested_at": datetime.utcnow(),
                "file_ids": [1],
                "shared_inputs": _build_shared_inputs(),
                "digest_mode": "systematic",
                "tone": "encouraging",
                "confirmed_plan": None,
            }
        )
    )

    assert "缺少已确认的构建方案" in result["error"]


def test_docgen_lane_summary_counts_chinese_markdown() -> None:
    final_markdown = "# 知识文档\n\n偏导数帮助我们观察多元函数在某一方向上的变化。"
    summary = build_docgen_lane_summary(
        {
            "digest_mode": "systematic",
            "chapter_materials": [
                {
                    "chapter_index": 1,
                    "title": "全景导论",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                    "local_hits": 2,
                    "web_hits": 1,
                    "fallback_used": True,
                    "curated_source_count": 2,
                    "planned_queries": ["偏导数 几何意义"],
                    "executed_queries": ["偏导数 几何意义", "偏导数 例题"],
                    "scraped_url_count": 1,
                    "document_count": 2,
                    "purify_used": True,
                    "research_ms": 120,
                }
            ],
            "chapter_drafts": [
                {
                    "chapter_index": 1,
                    "title": "全景导论",
                    "draft_ms": 80,
                    "word_count": count_words(final_markdown),
                    "placeholder_count": 1,
                }
            ],
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "全景导论",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                }
            ],
            "merged_markdown": final_markdown,
            "exam_questions": [{"question_index": 1}],
            "doc_ids": [101],
        },
        token_summary=DigestTokenSummary(),
    )

    assert summary["planned_query_count"] == 1
    assert summary["executed_query_count"] == 2
    assert summary["scraped_url_count"] == 1
    assert summary["research_document_count"] == 2
    assert summary["purify_chapter_count"] == 1
    assert summary["final_word_count"] == count_words(final_markdown)


def test_publish_staged_knowledge_docs_creates_new_version_and_supersedes_old(session, monkeypatch) -> None:
    class FakeContentStore:
        def __init__(self) -> None:
            self.text: dict[str, str] = {
                "demo/knowledge_markdowns/chapter_01_old.md": "旧内容",
                "demo/knowledge_markdowns/merged_knowledge_base.md": "旧合并文档",
            }

        async def write_text(self, key: str, content: str) -> None:
            self.text[key] = content

        async def delete_prefix(self, prefix: str) -> int:
            keys = [key for key in self.text if key.startswith(prefix)]
            for key in keys:
                self.text.pop(key, None)
            return len(keys)

        @staticmethod
        def knowledge_doc_key(subject: str, filename: str) -> str:
            return f"{subject}/knowledge_markdowns/{filename}"

        @staticmethod
        def knowledge_build_prefix(subject: str) -> str:
            return f"{subject}/knowledge_markdowns/_build/"

    fake_store = FakeContentStore()
    captured_manifest: dict[str, object] = {}

    @contextmanager
    def fake_managed_session():
        yield session

    def fake_run_store_sync(func, *args, **kwargs):
        kwargs.pop("default", None)
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def clear_current_files(subject: str) -> None:
        prefix = f"{subject}/knowledge_markdowns/"
        for key in list(fake_store.text):
            relative = key.removeprefix(prefix)
            if relative.startswith("versions/"):
                continue
            filename = relative.rsplit("/", 1)[-1]
            if filename.startswith("chapter_") or filename == "merged_knowledge_base.md":
                fake_store.text.pop(key, None)

    session.add(
        KnowledgeDoc(
            subject="demo",
            chapter_index=1,
            title="旧章节",
            markdown_content="旧内容",
            markdown_path="demo/knowledge_markdowns/chapter_01_old.md",
            version=1,
            version_no=1,
            is_current=True,
            status="published",
        )
    )
    session.commit()

    import app.workflows.digest.docgen.publish as publish_module

    monkeypatch.setattr(publish_module, "get_content_store", lambda: fake_store)
    monkeypatch.setattr(publish_module, "run_store_sync", fake_run_store_sync)
    monkeypatch.setattr(publish_module, "managed_session", fake_managed_session)
    monkeypatch.setattr(publish_module, "clear_current_published_knowledge_docs_files", clear_current_files)
    monkeypatch.setattr(
        publish_module,
        "write_knowledge_manifest",
        lambda subject, manifest: captured_manifest.setdefault(subject, manifest),
    )
    monkeypatch.setattr(publish_module, "update_knowledge_build_status", lambda *args, **kwargs: None)

    doc_ids = publish_staged_knowledge_docs(
        subject="demo",
        chapter_metadatas=[
            {
                "chapter_index": 1,
                "title": "新章节",
                "markdown": "# 新章节\n\n新的知识整理",
                "summary": "新摘要",
                "source_file_ids": [1],
                "digest_mode": "systematic",
            }
        ],
        chapter_assignments=[{"chapter_index": 1, "source_file_ids": [1]}],
        document_context={"subject": "demo", "digest_mode": "systematic", "tone": "encouraging"},
        user_prompt="生成新版本",
        requested_at=datetime.utcnow(),
        version_no=1,
        build_session_id="build-1",
    )

    docs = list(
        session.exec(
            select(KnowledgeDoc)
            .where(KnowledgeDoc.subject == "demo")
            .order_by(KnowledgeDoc.version_no, KnowledgeDoc.chapter_index)
        ).all()
    )
    assert len(doc_ids) == 1
    assert len(docs) == 2
    assert docs[0].is_current is False
    assert docs[0].status == "superseded"
    assert docs[0].superseded_at is not None
    assert docs[1].is_current is True
    assert docs[1].version_no == 2
    assert "versions/v0002/" in str(docs[1].markdown_path)
    assert "demo/knowledge_markdowns/versions/v0002/merged_knowledge_base.md" in fake_store.text
    assert "demo/knowledge_markdowns/merged_knowledge_base.md" in fake_store.text
    assert captured_manifest["demo"].version_no == 2
