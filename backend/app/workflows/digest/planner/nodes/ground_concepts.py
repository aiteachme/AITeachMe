"""Ground planner concepts with light retrieval before drafting."""

from __future__ import annotations

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.grounding import collect_planner_concept_briefing
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.shared.models import SharedInputs


def _merge_planner_topic_hints(shared_inputs: SharedInputs, topic_hints: list[str]) -> SharedInputs:
    if not topic_hints:
        return shared_inputs

    merged_candidates = list(shared_inputs.fast_hints.chapter_candidates)
    merged_topics = list(shared_inputs.subject_profile.key_topics)
    for item in topic_hints:
        if item not in merged_candidates:
            merged_candidates.append(item)
        if item not in merged_topics:
            merged_topics.append(item)

    next_inputs = shared_inputs.model_copy(deep=True)
    next_inputs.fast_hints.chapter_candidates = merged_candidates[:12]
    next_inputs.subject_profile.key_topics = merged_topics[:12]
    return next_inputs


def build_ground_concepts_node(*, context: WorkflowContext):
    async def ground_concepts_node(state: BuildPlannerState) -> dict:
        shared_inputs = state["shared_inputs"]
        await emit_progress(
            state,
            stage="ground_concepts",
            step="ground_concepts",
            detail="正在快速检索基础概念与知识框架，补充事实锚点...",
        )
        concept_brief = await collect_planner_concept_briefing(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            shared_inputs=shared_inputs,
            latest_plan=state.get("latest_plan"),
        )

        enhanced_inputs = _merge_planner_topic_hints(shared_inputs, concept_brief.topic_hints)
        local_message = f"已补充 {concept_brief.local_hit_count} 条本地概念锚点"
        web_message = (
            f"，{concept_brief.web_hit_count} 条外部概念锚点"
            if concept_brief.web_hit_count
            else ""
        )
        await emit_progress(
            state,
            stage="ground_concepts",
            step="ground_concepts",
            detail=f"{local_message}{web_message}。",
        )
        return {
            "shared_inputs": enhanced_inputs,
            "concept_queries": concept_brief.queries,
            "concept_briefing": concept_brief.briefing,
            "concept_topic_hints": concept_brief.topic_hints,
            "concept_local_hit_count": concept_brief.local_hit_count,
            "concept_web_hit_count": concept_brief.web_hit_count,
        }

    return ground_concepts_node


__all__ = ["build_ground_concepts_node"]
