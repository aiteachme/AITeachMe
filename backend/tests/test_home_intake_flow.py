import pytest

from app.workflows.interact.chat.lib import home_intake
from app.workflows.interact.chat.lib.intent import should_use_course_grounding


def test_home_intake_source_skips_course_grounding() -> None:
    assert not should_use_course_grounding(
        question="请讲解一下这门课的重点",
        source="home_intake",
        has_primary_context=False,
    )


@pytest.mark.anyio
async def test_home_intake_confirmation_runs_create_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_actions: list[dict | None] = []
    pending_action = {
        "name": "线性代数",
        "description": "矩阵与向量空间",
        "user_intent": "系统学习线性代数",
        "planner_prompt": "帮我构建线性代数学习计划",
        "attached_file_ids": ["file_a"],
    }

    async def fake_create_course_from_home_intake_tool(**kwargs):
        assert kwargs["name"] == "线性代数"
        assert kwargs["user_id"] == "user_1"
        assert kwargs["attached_file_ids"] == ["file_a", "file_b"]
        return {
            "ok": True,
            "data": {"course_id": "course_abc", "course_name": "线性代数"},
            "client_actions": [
                {
                    "type": "open_build_planner",
                    "payload": {
                        "course_id": "course_abc",
                        "initial_prompt": kwargs["planner_prompt"],
                        "auto_start": True,
                    },
                }
            ],
        }

    monkeypatch.setattr(home_intake, "_load_pending_action", lambda **_: pending_action)
    monkeypatch.setattr(
        home_intake,
        "_save_pending_action",
        lambda **kwargs: saved_actions.append(kwargs["pending_action"]),
    )
    monkeypatch.setattr(
        home_intake,
        "create_course_from_home_intake_tool",
        fake_create_course_from_home_intake_tool,
    )

    result = await home_intake.run_home_intake_turn(
        {
            "question": "确认创建",
            "session_id": "session_1",
            "user_id": "user_1",
            "attached_file_ids": ["file_b"],
            "model_override": "qwen-flash",
        },
    )

    assert "已创建" in result.assistant_response
    assert saved_actions == [None]
    assert result.client_actions == [
        {
            "type": "open_build_planner",
            "payload": {
                "course_id": "course_abc",
                "initial_prompt": "帮我构建线性代数学习计划",
                "auto_start": True,
                "model": "qwen-flash",
            },
        }
    ]
