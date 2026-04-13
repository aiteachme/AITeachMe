from __future__ import annotations

import asyncio
import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from sqlmodel import select

from app.models.knowledge_doc import KnowledgeDoc
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.common.context import create_langgraph_dev_context
from app.workflows.digest.docgen.nodes.inject_examine_node import build_inject_examine_node
from app.workflows.digest.docgen.nodes.load_context_node import build_load_context_node
from app.workflows.digest.docgen.publish import build_merged_markdown, publish_staged_knowledge_docs
from app.workflows.digest.observability import DigestTokenSummary, build_docgen_lane_summary
from app.workflows.digest.shared.contracts import parse_digest_confirmed_plan_contract
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
                normalized_content="Partial derivatives, gradients, and directional derivatives.",
                char_count=120,
                has_formulas=True,
                has_tables=False,
                has_images=False,
            )
        ],
        fast_hints=FastTopicHints(chapter_candidates=["Partial Derivative", "Gradient", "Directional Derivative"]),
        subject_profile=SubjectProfile(
            subject_name="Advanced Mathematics",
            discipline="Mathematics",
            sub_discipline="Multivariable Calculus",
            key_topics=["Partial Derivative", "Gradient", "Directional Derivative"],
            has_heavy_formulas=True,
        ),
    )


def test_load_context_requires_confirmed_plan() -> None:
    node = build_load_context_node(context=create_langgraph_dev_context("digest.docgen.contract"))
    result = asyncio.run(
        node(
            {
                "subject": "demo",
                "requested_at": datetime.now(timezone.utc),
                "file_ids": [1],
                "shared_inputs": _build_shared_inputs(),
                "digest_mode": "systematic",
                "tone": "encouraging",
                "confirmed_plan": None,
            }
        )
    )

    assert "DocGen" in result["error"]


def test_load_context_allows_search_only_docgen() -> None:
    node = build_load_context_node(context=create_langgraph_dev_context("digest.docgen.contract"))
    result = asyncio.run(
        node(
            {
                "subject": "demo",
                "requested_at": datetime.now(timezone.utc),
                "file_ids": [],
                "shared_inputs": SharedInputs(),
                "digest_mode": "systematic",
                "tone": "encouraging",
                "confirmed_plan": {
                    "digest_mode": "systematic",
                    "tone": "encouraging",
                    "user_goal": "Build a systematic note set for partial derivatives and gradients.",
                    "selected_skillpacks": ["find_resources", "explain_with_analogy"],
                    "plan_summary": "Search the web and build a chaptered study note.",
                    "chapter_plan": [
                        {
                            "chapter_index": 1,
                            "title": "Intuition and Definition",
                            "objective": "Build the first-layer understanding of partial derivatives.",
                            "search_queries": ["partial derivative geometric meaning", "partial derivative definition"],
                        }
                    ],
                },
            }
        )
    )

    assert result.get("error") is None
    assert result["course_type"] == "systematic"
    assert result["retrieval_profile"] == "docgen_systematic"
    assert result["teaching_action"] == "docgen_build"
    assert result["document_context"]["source_strategy"] == "web_first"
    assert result["document_context"]["course_type"] == "systematic"
    assert result["document_context"]["retrieval_profile"] == "docgen_systematic"
    assert result["selected_skillpacks"] == ["find_resources", "explain_with_analogy"]
    assert result["document_context"]["selected_skillpacks"] == ["find_resources", "explain_with_analogy"]
    assert result["confirmed_plan"]["course_type"] == "systematic"
    assert result["confirmed_plan"]["retrieval_profile"] == "docgen_systematic"
    assert result["confirmed_plan"]["selected_skillpacks"] == ["find_resources", "explain_with_analogy"]
    assert result["chapter_assignments"][0]["title"] == "Intuition and Definition"
    assert result["raw_chunks"] == []


def test_confirmed_plan_contract_applies_assignment_defaults() -> None:
    contract = parse_digest_confirmed_plan_contract(
        {
            "subject": "demo",
            "digest_mode": "systematic",
            "chapter_plan": [
                {
                    "chapter_index": 1,
                    "search_queries": ["partial derivative definition", "partial derivative definition", ""],
                }
            ],
            "selected_file_ids": ["1", "1", "invalid", 2],
            "selected_skillpacks": ["find_resources", "find_resources", "", "explain_with_analogy"],
        }
    )

    assignments = contract.to_chapter_assignments(default_source_file_ids=[7, 8])

    assert contract.selected_file_ids == [1, 2]
    assert contract.selected_skillpacks == ["find_resources", "explain_with_analogy"]
    assert len(assignments) == 1
    assignment = assignments[0]
    assert assignment["chapter_index"] == 1
    assert assignment["resolved_title"] == ""
    assert assignment["objective"] == ""
    assert assignment["required_elements"] == []
    assert assignment["search_queries"] == ["partial derivative definition"]
    assert assignment["writing_instructions"] == ""
    assert assignment["media_hints"] == {"images": [], "mermaid": [], "interactive": []}
    assert assignment["source_file_ids"] == [7, 8]
    assert assignment["execution_contract"]["target_word_count"] >= 10000
    assert assignment["execution_contract"]["min_word_count"] >= 6800
    assert assignment["execution_contract"]["repair_enabled"] is True


def test_docgen_lane_summary_counts_markdown() -> None:
    final_markdown = "# Knowledge Notes\n\nPartial derivatives describe local change along one axis."
    summary = build_docgen_lane_summary(
        {
            "digest_mode": "systematic",
            "course_type": "systematic",
            "chapter_materials": [
                {
                    "chapter_index": 1,
                    "title": "Rate of Change Intuition",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                    "local_hits": 2,
                    "web_hits": 1,
                    "fallback_used": True,
                    "curated_source_count": 2,
                    "planned_queries": ["partial derivative geometric meaning"],
                    "executed_queries": ["partial derivative geometric meaning", "partial derivative worked example"],
                    "read_url_count": 1,
                    "document_count": 2,
                    "purify_used": True,
                    "retrieval_profile": "docgen_systematic",
                    "applied_retrieval_profile": "docgen_systematic",
                    "configured_retrievers": ["local_rag", "tavily", "arxiv"],
                    "active_retrievers": ["local_rag", "tavily"],
                    "teaching_action": "chapter_research",
                    "research_ms": 120,
                }
            ],
            "chapter_drafts": [
                {
                    "chapter_index": 1,
                    "title": "Rate of Change Intuition",
                    "draft_ms": 80,
                    "word_count": count_words(final_markdown),
                    "placeholder_count": 1,
                    "teaching_action": "chapter_write",
                }
            ],
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "Rate of Change Intuition",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                }
            ],
            "mermaid_block_count": 1,
            "image_block_count": 0,
            "asset_count": 1,
            "asset_summary": {"mermaid": 1, "image": 0, "interactive_html": 0, "animation": 0},
            "document_context": {"source_strategy": "local_first"},
            "merged_markdown": final_markdown,
            "exam_questions": [{"question_index": 1}],
            "doc_ids": [101],
        },
        token_summary=DigestTokenSummary(),
    )

    assert summary["planned_query_count"] == 1
    assert summary["executed_query_count"] == 2
    assert summary["read_url_count"] == 1
    assert summary["research_document_count"] == 2
    assert summary["purify_chapter_count"] == 1
    assert summary["course_type"] == "systematic"
    assert summary["source_strategy"] == "local_first"
    assert summary["retrieval_profiles"] == ["docgen_systematic"]
    assert summary["applied_retrieval_profiles"] == ["docgen_systematic"]
    assert summary["teaching_actions"] == ["chapter_research", "chapter_write"]
    assert summary["configured_retriever_names"] == ["arxiv", "local_rag", "tavily"]
    assert summary["active_retriever_names"] == ["local_rag", "tavily"]
    assert summary["mermaid_count"] == 1
    assert summary["image_count"] == 0
    assert summary["asset_count"] == 1
    assert summary["asset_summary"] == {"mermaid": 1, "image": 0, "interactive_html": 0, "animation": 0}
    assert summary["final_word_count"] == count_words(final_markdown)


def test_build_merged_markdown_uses_explicit_teaching_hook() -> None:
    captured: dict[str, object] = {}

    def fake_overview(**kwargs):
        captured.update(kwargs)
        return "# Hooked Overview"

    with patch("app.workflows.digest.docgen.publish.build_learning_document_overview", new=fake_overview):
        merged = build_merged_markdown(
            [
                {
                    "chapter_index": 1,
                    "title": "Intuition and Definition",
                    "markdown": "# Intuition and Definition\n\nBody",
                }
            ],
            document_context={
                "subject": "demo",
                "digest_mode": "systematic",
                "tone": "encouraging",
                "user_goal": "Build a systematic note for partial derivatives.",
                "plan_summary": "Explain intuition first, then formal definition.",
                "source_strategy": "web_first",
            },
        )

    assert captured["subject"] == "demo"
    assert captured["digest_mode"] == "systematic"
    assert captured["source_strategy"] == "web_first"
    assert merged.startswith("# Hooked Overview")


def test_inject_examine_and_overview_prefer_resolved_title() -> None:
    chapter_metadatas = [
        {
            "chapter_index": 1,
            "title": "Chapter 1",
            "resolved_title": "Rate of Change Intuition",
            "markdown": "# Rate of Change Intuition\n\nBody",
            "summary": "Build intuition first.",
            "source_file_ids": [1],
            "source_details": [],
            "sources": [],
        }
    ]

    merged = build_merged_markdown(
        chapter_metadatas,
        document_context={
            "subject": "demo",
            "digest_mode": "systematic",
            "tone": "encouraging",
            "user_goal": "Build a systematic note for partial derivatives.",
            "plan_summary": "Organize the material by chapters.",
            "source_strategy": "local_first",
        },
    )
    node = build_inject_examine_node(context=create_langgraph_dev_context("digest.docgen.contract"))
    with patch("app.workflows.digest.docgen.nodes.inject_examine_node.update_knowledge_build_status"), patch(
        "app.workflows.digest.docgen.nodes.inject_examine_node.append_knowledge_build_recent_event"
    ):
        result = asyncio.run(
            node(
                {
                    "subject": "demo",
                    "requested_at": datetime.now(timezone.utc),
                    "digest_mode": "systematic",
                    "document_context": {
                        "subject": "demo",
                        "digest_mode": "systematic",
                        "tone": "encouraging",
                        "user_goal": "Build a systematic note for partial derivatives.",
                        "plan_summary": "Organize the material by chapters.",
                        "source_strategy": "local_first",
                    },
                    "chapter_metadatas": chapter_metadatas,
                }
            )
        )

    assert "Rate of Change Intuition" in merged
    assert "Rate of Change Intuition" in result["exam_questions"][0]["question"]


def test_publish_staged_knowledge_docs_creates_new_version_and_supersedes_old(session, monkeypatch) -> None:
    class FakeContentStore:
        def __init__(self) -> None:
            self.text: dict[str, str] = {
                "demo/knowledge_markdowns/chapter_01_old.md": "old chapter",
                "demo/knowledge_markdowns/merged_knowledge_base.md": "old merged file",
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
            title="Old Chapter",
            markdown_content="old content",
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
                "title": "Chapter 1",
                "resolved_title": "Rate of Change Intuition",
                "markdown": "# Rate of Change Intuition\n\nFresh knowledge note",
                "summary": "Fresh summary",
                "source_file_ids": [1],
                "digest_mode": "systematic",
            }
        ],
        chapter_assignments=[{"chapter_index": 1, "source_file_ids": [1]}],
        document_context={"subject": "demo", "digest_mode": "systematic", "tone": "encouraging"},
        user_prompt="Generate a refreshed version",
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
    assert docs[1].title == "Rate of Change Intuition"
    assert docs[1].version_no == 2
    assert "versions/v0002/" in str(docs[1].markdown_path)
    assert "chapter_01_Rate of Change Intuition.md" in str(docs[1].markdown_path)
    assert "demo/knowledge_markdowns/versions/v0002/merged_knowledge_base.md" in fake_store.text
    assert "demo/knowledge_markdowns/merged_knowledge_base.md" in fake_store.text
    assert captured_manifest["demo"].version_no == 2
    assert captured_manifest["demo"].chapter_titles == ["Rate of Change Intuition"]
