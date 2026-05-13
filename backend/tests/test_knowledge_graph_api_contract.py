from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api import knowledge as knowledge_api
from app.api.deps import CurrentUserContext
from app.schemas.common import PaginatedData
from app.schemas.knowledge import (
    ChunkContextResponse,
    FullGraphResponse,
    GraphEdgeResponse,
    KnowledgePathResponse,
    KnowledgeRelationExplanationResponse,
    KnowledgeRelationResponse,
    KnowledgeSubgraphResponse,
    KnowledgeUnitDetailResponse,
    KnowledgeUnitResponse,
)


@pytest.fixture
def knowledge_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(knowledge_api.router)

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="user-1", email=None, is_local=True)

    def override_get_db() -> object:
        return object()

    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context
    app.dependency_overrides[deps.get_db] = override_get_db

    from app.api import knowledge_graph as kg_api

    monkeypatch.setattr(kg_api, "get_course_record", lambda session, course_id, owner_user_id: object())

    with TestClient(app) as client:
        yield client


def _unit(unit_id: int = 1) -> KnowledgeUnitResponse:
    now = datetime.now(timezone.utc)
    return KnowledgeUnitResponse(
        id=unit_id,
        course_id="course_math00000000",
        knowledge_unit_type="concept",
        canonical_name=f"Unit {unit_id}",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )


def _relation() -> KnowledgeRelationResponse:
    return KnowledgeRelationResponse(
        id=10,
        course_id="course_math00000000",
        source_node_id=1,
        source_node_name="Unit 1",
        source_node_type="concept",
        target_node_id=2,
        target_node_name="Unit 2",
        target_node_type="concept",
        edge_type="prerequisite",
        weight=0.8,
        confidence=0.7,
    )


def test_knowledge_graph_query_endpoints_delegate_with_normalized_course(
    knowledge_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import knowledge_graph as kg_api

    calls: list[tuple[str, dict[str, object]]] = []

    def record(name: str, value):
        def wrapped(session, **kwargs):
            calls.append((name, kwargs))
            return value

        return wrapped

    monkeypatch.setattr(
        kg_api,
        "get_knowledge_units",
        record(
            "units",
            PaginatedData(items=[_unit()], page=1, size=20, total=1, pages=1),
        ),
    )
    monkeypatch.setattr(kg_api, "get_knowledge_unit_detail", record("detail", _detail_response()))
    monkeypatch.setattr(kg_api, "get_knowledge_unit_relations", record("relations", [_relation()]))
    monkeypatch.setattr(kg_api, "find_knowledge_path", record("path", KnowledgePathResponse(found=True, nodes=[_unit()], edges=[])))
    monkeypatch.setattr(kg_api, "get_focus_subgraph", record("subgraph", KnowledgeSubgraphResponse(nodes=[_unit()], edges=[])))
    monkeypatch.setattr(
        kg_api,
        "explain_relation_path",
        record(
            "explain",
            KnowledgeRelationExplanationResponse(
                path=KnowledgePathResponse(found=True, nodes=[_unit(), _unit(2)], edges=[_relation()]),
                evidence=[],
            ),
        ),
    )
    monkeypatch.setattr(
        kg_api,
        "get_full_graph",
        record(
            "full",
            FullGraphResponse(
                nodes=[_unit()],
                edges=[
                    GraphEdgeResponse(
                        id=1,
                        source_node_id=1,
                        target_node_id=2,
                        edge_type="prerequisite",
                        weight=1.0,
                        confidence=0.9,
                    )
                ],
            ),
        ),
    )
    monkeypatch.setattr(
        kg_api,
        "get_chunk_context",
        record(
            "chunk",
            ChunkContextResponse(
                chunk_id=99,
                file_id="file-1",
                document_title="Doc",
                chunk_title="Chunk",
                chunk_header_path="Root > Chunk",
                chunk_content="content",
            ),
        ),
    )

    responses = [
        knowledge_client.post("/api/v1/courses/course_math00000000/knowledge/graph/knowledge-units", json={}),
        knowledge_client.post(
            "/api/v1/courses/course_math00000000/knowledge/graph/knowledge-units/detail",
            json={"knowledge_unit_id": 1},
        ),
        knowledge_client.post(
            "/api/v1/courses/course_math00000000/knowledge/graph/knowledge-units/relations",
            json={"knowledge_unit_id": 1},
        ),
        knowledge_client.post(
            "/api/v1/courses/course_math00000000/knowledge/graph/knowledge-units/path",
            json={"source_knowledge_unit_id": 1, "target_knowledge_unit_id": 2},
        ),
        knowledge_client.post(
            "/api/v1/courses/course_math00000000/knowledge/graph/subgraph",
            json={"center_knowledge_unit_id": 1},
        ),
        knowledge_client.post(
            "/api/v1/courses/course_math00000000/knowledge/graph/relations/explain",
            json={"source_knowledge_unit_id": 1, "target_knowledge_unit_id": 2},
        ),
        knowledge_client.post("/api/v1/courses/course_math00000000/knowledge/graph/full"),
        knowledge_client.post(
            "/api/v1/courses/course_math00000000/knowledge/chunks/context",
            json={"chunk_id": 99},
        ),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["data"]["items"][0]["canonical_name"] == "Unit 1"
    assert responses[2].json()["data"][0]["edge_type"] == "prerequisite"
    assert responses[6].json()["data"]["edges"][0]["confidence"] == 0.9
    assert responses[7].json()["data"]["chunk_id"] == 99
    assert [name for name, _kwargs in calls] == [
        "units",
        "detail",
        "relations",
        "path",
        "subgraph",
        "explain",
        "full",
        "chunk",
    ]
    assert all(kwargs["course_id"] == "course_math00000000" for _name, kwargs in calls)


def test_retrieval_debug_skips_search_when_notice_is_present(
    knowledge_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import knowledge_graph as kg_api

    async def fake_notice(course_id: str) -> str:
        assert course_id == "course_math00000000"
        return "index disabled"

    async def unexpected_search(*args, **kwargs):
        raise AssertionError("search should not run when a notice is present")

    monkeypatch.setattr(kg_api, "get_knowledge_search_notice", fake_notice)
    monkeypatch.setattr(kg_api, "search_knowledge", unexpected_search)

    response = knowledge_client.post(
        "/api/v1/courses/course_math00000000/knowledge/retrieval/debug",
        json={"query": " unit context ", "top_k": 3, "enable_rerank": False, "preview_chars": 120},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["query"] == "unit context"
    assert payload["notice"] == "index disabled"
    assert payload["items"] == []
    assert payload["result_count"] == 0


def test_retrieval_debug_formats_chunk_previews(
    knowledge_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import knowledge_graph as kg_api

    async def no_notice(course_id: str) -> None:
        assert course_id == "course_math00000000"
        return None

    async def fake_search(query: str, course_id: str, *, top_k: int, enable_rerank: bool):
        assert (query, course_id, top_k, enable_rerank) == (
            "matrix",
            "course_math00000000",
            2,
            True,
        )
        return [
            SimpleNamespace(
                chunk_id=7,
                file_id="file-1",
                title="Linear Algebra",
                header_path="Chapter > Matrices",
                score=0.87654,
                source="vector",
                content="matrix content that should be clipped",
            )
        ]

    monkeypatch.setattr(kg_api, "get_knowledge_search_notice", no_notice)
    monkeypatch.setattr(kg_api, "search_knowledge", fake_search)

    response = knowledge_client.post(
        "/api/v1/courses/course_math00000000/knowledge/retrieval/debug",
        json={"query": "matrix", "top_k": 2, "preview_chars": 120},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["result_count"] == 1
    assert payload["items"][0]["chunk_id"] == 7
    assert payload["items"][0]["content_preview"] == "matrix content that should be clipped"


def _detail_response() -> KnowledgeUnitDetailResponse:
    now = datetime.now(timezone.utc)
    return KnowledgeUnitDetailResponse(
        id=1,
        course_id="course_math00000000",
        knowledge_unit_type="concept",
        canonical_name="Unit 1",
        normalized_name="unit 1",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
