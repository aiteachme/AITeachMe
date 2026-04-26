from sqlmodel import Session, SQLModel, create_engine

from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
import app.workflows.digest.kg_doc_sync.lib.incremental_sync as incremental_sync


def test_find_unit_with_rag_reuses_existing_unit(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_search_knowledge(query, subject_id, *, top_k=5, enable_rerank=True):
        class Hit:
            chunk_id = 1
            document_id = 1
            title = "勾股定理"
            header_path = "勾股定理"
            content = "直角三角形两直角边平方和等于斜边平方"
            score = 0.95
            source = "vector"

        return [Hit()]

    async def fake_aembed_texts(texts, *, batch_size=None, soft_fail=False):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(incremental_sync, "search_knowledge", fake_search_knowledge)
    monkeypatch.setattr(incremental_sync, "aembed_texts", fake_aembed_texts)

    with Session(engine) as session:
        session.add(
            KnowledgeUnit(
                subject="math",
                knowledge_unit_type="theorem",
                canonical_name="勾股定理",
                normalized_name="勾股定理",
                summary="直角三角形两直角边平方和等于斜边平方",
                body_markdown="直角三角形两直角边平方和等于斜边平方",
                status="active",
            )
        )
        session.commit()

        item = MarkdownKnowledgeUnit(
            anchor="ku_pythagorean-theorem",
            name="勾股定理",
            knowledge_unit_type="theorem",
            summary="直角三角形两直角边平方和等于斜边平方",
            body_markdown="直角三角形两直角边平方和等于斜边平方",
        )
        matched = incremental_sync._find_unit_with_rag(
            session,
            subject="math",
            item=item,
            knowledge_unit_type="theorem",
        )

    assert matched is not None
    assert matched.canonical_name == "勾股定理"
