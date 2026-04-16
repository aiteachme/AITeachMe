from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.workflow.context import create_langgraph_dev_context
from app.workflows.digest.planner.lib.research_probe import (
    EvidenceBrief,
    LearningIntentProfile,
    PlanSketch,
    PlannerQuery,
    ResearchProbePlan,
)
from app.workflows.digest.planner.lib.plans import build_fallback_plan
from app.workflows.digest.planner.lib.research_probe import build_fallback_plan_sketch
from app.workflows.digest.planner.lib.grounding import (
    build_planner_concept_queries,
    collect_planner_concept_briefing,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.graph import build_planner_graph
from app.workflows.digest.planner import nodes as planner_nodes
from app.workflows.digest.planner.nodes.generate_plan_preview import build_generate_plan_preview_node
from app.workflows.digest.planner.prompts import build_plan_composer_messages
from app.workflows.digest.planner.state import BuildPlannerGraphInput
from app.workflows.digest.common.models import DigestMaterialContext, FastTopicHints, SectionPacket, SharedInputs, SubjectProfile


def _build_shared_inputs() -> SharedInputs:
    return SharedInputs(
        section_packets=[
            SectionPacket(
                digest_chunk_uid="chunk_1",
                source_file_id=1,
                source_filename="math.md",
                chunk_index=0,
                page_num=1,
                title="极限",
                header_path="第一章 > 极限",
                level=2,
                normalized_content="极限描述变量逼近某个值时的变化趋势，连续与导数都以它为基础。",
                preview="极限描述变量逼近某个值时的变化趋势。",
                char_count=32,
            )
        ],
        fast_hints=FastTopicHints(chapter_candidates=["极限", "连续", "导数"]),
        subject_profile=SubjectProfile(
            subject_slug="subj_math",
            subject_name="高等数学",
            discipline="数学",
            sub_discipline="微积分",
            key_topics=["极限", "导数", "微分"],
            has_heavy_formulas=True,
        ),
    )


def test_build_planner_concept_queries_prefers_subject_and_topic_hints() -> None:
    queries = build_planner_concept_queries(
        subject="subj_math",
        user_goal="系统学习极限、导数与微分的基础概念",
        shared_inputs=_build_shared_inputs(),
        latest_plan={
            "chapter_plan": [
                {"title": "极限：定义与性质"},
                {"title": "导数：概念与运算"},
            ]
        },
    )

    assert queries[0] == "高等数学 基础概念 知识框架"
    assert len(queries) <= 4
    assert any("极限 定义 关键性质" == item for item in queries)
    assert any("导数 定义 关键性质" == item for item in queries)


def test_digest_material_context_accepts_new_and_legacy_names() -> None:
    context = DigestMaterialContext(
        material_sections=_build_shared_inputs().section_packets,
        material_hints=FastTopicHints(chapter_candidates=["函数"]),
        learning_domain_profile=SubjectProfile(subject_name="数学"),
    )
    legacy = SharedInputs(
        section_packets=context.material_sections,
        fast_hints=context.material_hints,
        subject_profile=context.learning_domain_profile,
    )

    assert context.section_packets == context.material_sections
    assert context.fast_hints.chapter_candidates == ["函数"]
    assert context.subject_profile.subject_name == "数学"
    assert legacy.material_sections == context.material_sections
    assert legacy.learning_domain_profile.subject_name == "数学"


def test_collect_planner_concept_briefing_merges_local_and_web_evidence(monkeypatch) -> None:
    shared_inputs = _build_shared_inputs()
    queries = build_planner_concept_queries(
        subject="subj_math",
        user_goal="系统学习极限、导数与微分的基础概念",
        shared_inputs=shared_inputs,
    )
    responses = {
        ("local_rag", queries[0]): [
            SearchResult(
                url="local://section/0",
                title="高等数学 - 基础框架",
                snippet="高等数学通常先梳理极限、连续、导数和微分之间的关系。",
                source="local_rag",
            )
        ],
        ("local_rag", queries[1]): [
            SearchResult(
                url="local://section/1",
                title="极限 - 定义与性质",
                snippet="极限研究变量在逼近过程中的稳定趋势，是连续与导数的前置概念。",
                source="local_rag",
            )
        ],
        ("duckduckgo", queries[0]): [
            SearchResult(
                url="https://example.com/gaodengshuxue",
                title="高等数学 - 百度百科",
                snippet="高等数学是研究函数、极限、微分和积分的基础课程。",
                source="duckduckgo",
            )
        ],
        ("duckduckgo", queries[1]): [
            SearchResult(
                url="https://example.com/jixian",
                title="极限 - 百度百科",
                snippet="极限是分析学中的核心概念，用来描述变化过程的逼近结果。",
                source="duckduckgo",
            )
        ],
    }

    class FakeRetriever:
        def __init__(self, name: str):
            self.name = name

        async def traced_search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            return list(responses.get((self.name, query), []))[:max_results]

    monkeypatch.setattr(
        "app.workflows.digest.planner.lib.grounding.get_settings",
        lambda: SimpleNamespace(
            planner=SimpleNamespace(grounding_timeout_s=10.0),
            search=SimpleNamespace(provider_timeout_s=6.0),
        ),
    )
    monkeypatch.setattr(
        "app.workflows.digest.planner.lib.grounding.get_retriever",
        lambda name, **kwargs: FakeRetriever(name),
    )
    monkeypatch.setattr(
        "app.workflows.digest.planner.lib.grounding.read_urls",
        lambda urls: asyncio.sleep(
            0,
            result=[
                ScrapedPage(
                    url="https://example.com/gaodengshuxue",
                    title="高等数学 - 百度百科",
                    content="高等数学研究函数、极限、微分和积分的基础理论，并强调这些概念之间的结构关系。",
                    success=True,
                ),
                ScrapedPage(
                    url="https://example.com/jixian",
                    title="极限 - 百度百科",
                    content="极限描述变量在某个过程中逐步逼近目标值，是连续与导数的前置概念。",
                    success=True,
                ),
            ],
        ),
    )

    briefing = asyncio.run(
        collect_planner_concept_briefing(
            subject="subj_math",
            user_goal="系统学习极限、导数与微分的基础概念",
            shared_inputs=shared_inputs,
        )
    )

    assert briefing.local_hit_count == 2
    assert briefing.web_hit_count == 2
    assert briefing.web_read_count == 2
    assert "快速概念检索锚点：" in briefing.briefing
    assert "外部网页仅用于校验概念范围" in briefing.briefing
    assert "百度百科" not in briefing.briefing
    assert "建议优先覆盖的概念锚点" in briefing.briefing
    assert "极限" in briefing.topic_hints


def test_planner_graph_compiles_with_v3_nodes() -> None:
    compiled = build_planner_graph(
        context=create_langgraph_dev_context("digest.planner.concept_grounding_test")
    ).compile()

    node_ids = {node.id for node in compiled.get_graph().nodes.values()}

    assert "prepare_material_context" in node_ids
    assert "generate_plan_preview" in node_ids
    assert "probe_supporting_evidence" in node_ids
    assert "compose_plan_contract" in node_ids
    assert "finalize_plan_contract" in node_ids


def test_planner_input_schema_keeps_stream_callbacks() -> None:
    annotations = BuildPlannerGraphInput.__annotations__

    assert "progress_callback" in annotations
    assert "token_callback" in annotations
    assert "planner_session_id" in annotations


def test_planner_node_aliases_point_to_current_implementations() -> None:
    assert planner_nodes.build_generate_plan_preview_node is planner_nodes.build_bootstrap_plan_brief_node
    assert planner_nodes.build_probe_supporting_evidence_node is planner_nodes.build_probe_evidence_node
    assert planner_nodes.build_compose_plan_contract_node is planner_nodes.build_compose_build_plan_node


def test_planner_event_helpers_support_sync_and_async_callbacks() -> None:
    events: list[dict] = []
    tokens: list[str] = []

    async def progress_callback(payload: dict) -> None:
        events.append(payload)

    def token_callback(token: str) -> None:
        tokens.append(token)

    asyncio.run(
        emit_planner_event(
            {"progress_callback": progress_callback},
            event="planner.test",
            detail="测试事件",
            payload={"count": 1},
        )
    )
    asyncio.run(emit_planner_token({"token_callback": token_callback}, "草稿"))

    assert events == [
        {
            "stage": "planner.test",
            "step": "planner.test",
            "event": "planner.test",
            "detail": "测试事件",
            "count": 1,
        }
    ]
    assert tokens == ["草稿"]


def test_generate_plan_preview_streams_sketch_and_extracts_intent(monkeypatch) -> None:
    async def fake_stream(*_args, **_kwargs):
        for token in ["高等数学规划\n", "1. 梳理极限核心概念\n"]:
            yield token

    intent = LearningIntentProfile(
        goal_type="systematic_learning",
        research_probe_plan=ResearchProbePlan(
            local_queries=[PlannerQuery(query="极限 核心概念", purpose="校准本地概念", expected_signal="定义")],
            web_queries=[],
        ),
    )
    monkeypatch.setattr(
        "app.workflows.digest.planner.nodes.bootstrap_plan_brief.acompletion_stream",
        fake_stream,
    )
    monkeypatch.setattr(
        "app.workflows.digest.planner.nodes.bootstrap_plan_brief.acompletion_with_fallback",
        AsyncMock(return_value=intent),
    )

    tokens: list[str] = []
    events: list[dict] = []
    node = build_generate_plan_preview_node(context=create_langgraph_dev_context("digest.planner.preview_test"))
    result = asyncio.run(
        node(
            {
                "subject": "subj_math",
                "user_goal": "系统学习极限",
                "digest_mode": "systematic",
                "tone": "encouraging",
                "material_context": _build_shared_inputs(),
                "message_history": ["系统学习极限"],
                "selected_skillpacks": [],
                "token_callback": lambda token: tokens.append(token),
                "progress_callback": lambda payload: events.append(payload),
            }
        )
    )

    assert "".join(tokens).startswith("高等数学规划")
    assert result["plan_sketch_markdown"].startswith("高等数学规划")
    assert result["plan_sketch"]["research_tasks"]
    assert result["learning_intent_profile"]["goal_type"] == "systematic_learning"
    assert result["research_probe_plan"]["local_queries"][0]["query"] == "极限 核心概念"
    assert any(event["event"] == "planner.intent.ready" for event in events)


def test_plan_composer_prompt_keeps_revision_context() -> None:
    messages = build_plan_composer_messages(
        subject="subj_math",
        user_goal="系统学习极限",
        digest_mode="systematic",
        tone="encouraging",
        material_context=_build_shared_inputs(),
        plan_sketch=PlanSketch(
            research_tasks=["梳理极限和连续的关系"],
            provisional_chapters=["极限与连续"],
        ),
        intent_profile=LearningIntentProfile(
            goal_type="systematic_learning",
            success_criteria=["形成清晰大纲"],
        ),
        evidence_brief=EvidenceBrief(concept_briefing="本地资料覆盖极限定义。"),
        message_history=["第一版太泛", "请更偏考试重点"],
        latest_plan={
            "plan_summary": "上一版偏系统综述。",
            "chapter_plan": [{"title": "泛化章节"}],
        },
    )

    prompt = messages[-1]["content"]

    assert "请更偏考试重点" in prompt
    assert "上一版偏系统综述" in prompt
    assert "上一版章节数：1" in prompt


def test_fallback_plan_sketch_uses_markdown_contract() -> None:
    draft = build_fallback_plan(
        subject="subj_math",
        user_goal="系统学习极限",
        digest_mode="systematic",
        tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )
    sketch = build_fallback_plan_sketch(draft)

    assert sketch.raw_text.startswith("# 构建方案")
    assert "## 研究任务" in sketch.raw_text
    assert "## 暂定章节" in sketch.raw_text
