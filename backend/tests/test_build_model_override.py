from __future__ import annotations

from app.models.build_planner import ConfirmedBuildPlan
from app.shared.infra.llm_support.model_choices import build_runtime_model_override_snapshot
from app.workflows.digest.docgen.lib.build_lifecycle import _build_confirmed_plan_payload


def test_confirmed_plan_payload_preserves_model_override() -> None:
    plan = ConfirmedBuildPlan(
        id="plan_1",
        course_id="course_1",
        planner_session_id="planner_1",
        user_id="user_1",
        user_prompt="学习线性代数",
        digest_mode="sprint",
        plan_json={
            "course": "线性代数",
            "user_prompt": "学习线性代数",
            "digest_mode": "sprint",
            "chapter_plan": [],
            "build_constraints": {},
            "plan_summary": "一份线性代数学习计划",
            "model_override": "deepseek-v4-flash",
        },
    )

    payload = _build_confirmed_plan_payload(plan, fallback_course_name="线性代数")

    assert payload["model_override"] == "deepseek-v4-flash"


def test_runtime_model_override_snapshot_patches_main_model_slots() -> None:
    snapshot = build_runtime_model_override_snapshot("deepseek-v4-flash")

    assert snapshot is not None
    assert snapshot.settings.models.reason == "deepseek-v4-flash"
    assert snapshot.settings.models.primary == "deepseek-v4-flash"
    assert snapshot.settings.models.light == "deepseek-v4-flash"
