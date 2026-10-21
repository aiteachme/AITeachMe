from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from app.models import ChatSession
from app.utils.course import GLOBAL_COURSE
from app.workflows.interact.chat import graph as interact_graph
from app.workflows.interact.chat.lib import home_intake
from app.workflows.interact.chat.lib.intent import ChatPromptScene, resolve_prompt_scene, should_use_course_grounding
from app.workflows.interact.chat.nodes import persist as persist_node
from app.workflows.interact.chat.lib.types import RecentMessage


@pytest.fixture(autouse=True)
def intake_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ChatSession.__table__.create(engine)

    @contextmanager
    def session_scope():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(home_intake, "managed_session", session_scope)
    yield engine
    engine.dispose()


def test_home_intake_source_skips_course_grounding() -> None:
    assert not should_use_course_grounding(
        question="请讲解一下这门课的重点",
        source="home_intake",
        has_primary_context=False,
    )


def test_explicit_chat_scene_controls_prompt_scene() -> None:
    assert resolve_prompt_scene(
        question="帮我查询最新基础教育课程改革政策",
        scene="web_research",
        source="web_research",
        course_id="global",
        has_primary_context=False,
    ) == ChatPromptScene.WEB_RESEARCH

    assert resolve_prompt_scene(
        question="这段是什么意思？",
        scene="document_selection",
        source="quick_chat",
        course_id="course_1",
        has_primary_context=True,
    ) == ChatPromptScene.DOCUMENT_SELECTION

    assert should_use_course_grounding(
        question="这份资料讲的 CPU 是什么？",
        scene="library_selection",
        source="library_selection",
        has_primary_context=False,
    )
    assert resolve_prompt_scene(
        question="这份资料讲的 CPU 是什么？",
        scene="library_selection",
        source="library_selection",
        course_id="global",
        has_primary_context=False,
    ) == ChatPromptScene.LIBRARY_LEARNING

    assert should_use_course_grounding(
        question="这份资料主要讲什么？",
        scene="global_assistant",
        source="library_selection",
        has_primary_context=False,
    )
    assert resolve_prompt_scene(
        question="这份资料主要讲什么？",
        scene="global_assistant",
        source="library_selection",
        course_id="global",
        has_primary_context=False,
    ) == ChatPromptScene.LIBRARY_LEARNING

    assert should_use_course_grounding(
        question="What does this uploaded file cover?",
        scene="global_assistant",
        source="library_selection:file_123",
        has_primary_context=False,
    )
    assert resolve_prompt_scene(
        question="What does this uploaded file cover?",
        scene="global_assistant",
        source="library_selection:file_123",
        course_id="global",
        has_primary_context=False,
    ) == ChatPromptScene.LIBRARY_LEARNING

    assert not should_use_course_grounding(
        question="Search the latest course policy.",
        scene="web_research",
        source="library_selection:file_123",
        has_primary_context=False,
    )
    assert resolve_prompt_scene(
        question="Search the latest course policy.",
        scene="web_research",
        source="library_selection:file_123",
        course_id="global",
        has_primary_context=False,
    ) == ChatPromptScene.WEB_RESEARCH

    assert not should_use_course_grounding(
        question="Build a course from these materials.",
        scene="home_intake",
        source="library_selection:file_123",
        has_primary_context=False,
    )
    assert resolve_prompt_scene(
        question="Build a course from these materials.",
        scene="home_intake",
        source="library_selection:file_123",
        course_id="global",
        has_primary_context=False,
    ) == ChatPromptScene.GLOBAL_ASSISTANT


def test_home_intake_rejects_unrelated_or_explicit_tool_requests() -> None:
    cases = [
        {
            "scene": "global_assistant",
            "source": "global_assistant",
            "course_id": "global",
            "question": "基础教育课程改革有哪些最新政策变化？",
        },
        {
            "scene": "home_intake",
            "source": "home_intake",
            "course_id": "global",
            "question": "使用ask_user_options问我问题",
        },
    ]

    for case in cases:
        assert not home_intake.should_use_home_intake_flow(**case), case["question"]


def test_creation_followup_routes_short_answer_to_home_intake() -> None:
    assert home_intake.should_use_home_intake_flow(
        scene="global_assistant",
        source="global_assistant",
        course_id="global",
        question="一年级上册",
        recent_messages=[
            RecentMessage(
                role="assistant",
                content="可以，我先确认一下：你想创建哪门学科？希望它重点帮你解决什么学习目标？",
            )
        ],
    )


def test_graph_routes_home_intake_without_hijacking_library_retrieval() -> None:
    cases = [
        ("global_assistant", "帮我构建一门计算机组成原理期末冲刺课", "home_intake"),
        ("library_selection", "这份资料主要讲什么？", "continue"),
    ]

    for source, question, expected in cases:
        route = interact_graph._route_after_history_step(
            {
                "course_id": "global",
                "scene": "global_assistant",
                "source": source,
                "question": question,
                "recent_messages": [],
                "error": None,
            }
        )

        assert route == expected, source


def test_client_action_only_turn_can_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_create_message_pair(_session, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        return SimpleNamespace(), SimpleNamespace(turn_id="turn_action")

    logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(persist_node, "create_message_pair", fake_create_message_pair)

    persist_turn = persist_node.build_persist_turn_node(
        context=SimpleNamespace(get_logger=lambda: logger),
        session=object(),
    )
    result = persist_turn(
        {
            "course_id": "global",
            "user_id": "user_1",
            "session_id": "session_1",
            "question": "使用ask_user_options问我问题",
            "assistant_response": "",
            "client_actions": [{"type": "ask_user_options", "payload": {"question": "选一个"}}],
            "contexts": None,
        }
    )

    assert result["turn_id"] == "turn_action"
    assert calls[0]["assistant_content"] == ""
    assert calls[0]["client_actions"] == [{"type": "ask_user_options", "payload": {"question": "选一个"}}]


@pytest.mark.anyio
async def test_home_intake_short_followup_saves_pending_action(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_actions: list[dict | None] = []

    async def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("LLM classifier should not be needed for a creation follow-up answer")

    monkeypatch.setattr(home_intake, "_load_pending_action", lambda **_: None)
    monkeypatch.setattr(
        home_intake,
        "_save_pending_action",
        lambda **kwargs: saved_actions.append(kwargs["pending_action"]),
    )
    monkeypatch.setattr(home_intake, "acompletion", fail_if_called)

    result = await home_intake.run_home_intake_turn(
        {
            "question": "一年级上册",
            "session_id": "session_1",
            "user_id": "user_1",
            "attached_file_ids": [],
            "recent_messages": [
                RecentMessage(
                    role="assistant",
                    content="可以，我先确认一下：你想创建哪门学科？希望它重点帮你解决什么学习目标？",
                )
            ],
        },
    )

    assert "确认创建" in result.assistant_response
    assert "已创建" not in result.assistant_response
    assert saved_actions[0]["name"] == "一年级上册"


@pytest.mark.anyio
async def test_home_intake_fallback_ready_intent_keeps_required_reply_field(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_actions: list[dict | None] = []

    async def fail_classifier(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(home_intake, "_load_pending_action", lambda **_: None)
    monkeypatch.setattr(
        home_intake,
        "_save_pending_action",
        lambda **kwargs: saved_actions.append(kwargs["pending_action"]),
    )
    monkeypatch.setattr(home_intake, "acompletion", fail_classifier)

    result = await home_intake.run_home_intake_turn(
        {
            "question": "帮我构建计算机组成原理期末冲刺课程",
            "session_id": "session_1",
            "user_id": "user_1",
            "attached_file_ids": ["file_1"],
            "recent_messages": [],
        },
    )

    assert "确认创建" in result.assistant_response
    assert saved_actions[0] is not None
    assert saved_actions[0]["tool"] == "create_course_from_home_intake"
    assert saved_actions[0]["attached_file_ids"] == ["file_1"]


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
            "model_override": "primary",
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
                "model": "primary",
            },
        }
    ]


@pytest.mark.anyio
async def test_home_intake_keeps_materials_through_clarification_and_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    intake_db,
) -> None:
    with Session(intake_db) as session:
        session.add(ChatSession(id="intake", course_id=GLOBAL_COURSE, user_id="user_1", meta_json={"other": "preserved"}))
        session.commit()

    classified_files: list[list[str]] = []
    created_files: list[list[str]] = []

    async def classify(**kwargs):
        classified_files.append(kwargs["attached_file_ids"])
        if len(classified_files) == 1:
            return home_intake.HomeIntakeIntent(intent="clarify", assistant_reply="更侧重概念还是应用？")
        return home_intake.HomeIntakeIntent(
            intent="create_course", assistant_reply="", course_name="一次函数", ready_to_create=True,
            user_intent="识别斜率与纵截距", planner_prompt="仅一章，结合已选资料复习一次函数。",
        )

    async def create(**kwargs):
        created_files.append(kwargs["attached_file_ids"])
        return {"data": {"course_id": "course_new", "course_name": "一次函数"}}

    monkeypatch.setattr(home_intake, "_classify_home_intake_intent", classify)
    monkeypatch.setattr(home_intake, "create_course_from_home_intake_tool", create)
    state = {"course_id": GLOBAL_COURSE, "session_id": "intake", "user_id": "user_1"}

    await home_intake.run_home_intake_turn({**state, "question": "先讨论资料", "attached_file_ids": ["file_a"]})
    result = await home_intake.run_home_intake_turn(
        {**state, "question": "只复习一次函数", "attached_file_ids": ["file_b", "file_a"]},
    )
    assert "关联当前选择的 2 份资料" in result.assistant_response
    await home_intake.run_home_intake_turn({**state, "question": "确认创建", "attached_file_ids": []})

    assert classified_files == [["file_a"], ["file_a", "file_b"]]
    assert created_files == [["file_a", "file_b"]]
    with Session(intake_db) as session:
        assert session.get(ChatSession, "intake").meta_json["other"] == "preserved"


def test_home_intake_materials_are_scoped_to_owned_session(intake_db) -> None:
    with Session(intake_db) as session:
        session.add_all([
            ChatSession(id="first", course_id=GLOBAL_COURSE, user_id="user_1", meta_json={"home_intake": {"attached_file_ids": ["file_a"]}}),
            ChatSession(id="second", course_id=GLOBAL_COURSE, user_id="user_1"),
        ])
        session.commit()

    assert home_intake._remember_attached_file_ids(session_id="first", user_id="user_1", file_ids=[]) == ["file_a"]
    assert home_intake._remember_attached_file_ids(session_id="second", user_id="user_1", file_ids=[]) == []
    assert home_intake._remember_attached_file_ids(session_id="first", user_id="user_2", file_ids=["file_b"]) == ["file_b"]
    assert home_intake._remember_attached_file_ids(session_id="first", user_id="user_1", file_ids=[]) == ["file_a"]
