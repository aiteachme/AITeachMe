import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.repositories.chats_repo import create_chat_session, create_message_pair
from app.workflows.interact.chat import use_cases
from app.workflows.interact.chat.use_cases import list_chat_sessions


def anyio_backend() -> str:
    return "asyncio"


def test_list_chat_sessions_includes_latest_doc_selection_target():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        normal = create_chat_session(
            session,
            subject="demo",
            user_id="user-1",
            title="普通对话",
        )
        quick = create_chat_session(
            session,
            subject="demo",
            user_id="user-1",
            title="划词对话",
            source="quick_chat",
        )
        create_message_pair(
            session,
            subject="demo",
            user_id="user-1",
            session_id=quick.id,
            user_content="旧问题",
            assistant_content="旧回答",
            source="quick_chat",
            anchor_id="old-anchor",
            selected_text="旧划词",
        )
        create_message_pair(
            session,
            subject="demo",
            user_id="user-1",
            session_id=quick.id,
            user_content="新问题",
            assistant_content="新回答",
            source="quick_chat",
            anchor_id="new-anchor",
            selected_text="新划词",
        )
        create_message_pair(
            session,
            subject="demo",
            user_id="user-1",
            session_id=normal.id,
            user_content="普通问题",
            assistant_content="普通回答",
        )

        page = list_chat_sessions(
            session,
            subject="demo",
            user_id="user-1",
            page=1,
            size=10,
        )

    items = {item.id: item for item in page.items}
    assert items[quick.id].anchor_id == "new-anchor"
    assert items[quick.id].selected_text == "新划词"
    assert items[normal.id].anchor_id is None
    assert items[normal.id].selected_text is None


@pytest.mark.anyio
async def test_generate_session_title_uses_llm_and_cleans_output(monkeypatch):
    async def fake_completion(messages, **kwargs):
        assert kwargs["model"] == "light"
        assert kwargs["call_purpose"].value == "summarize"
        assert "用户问题：怎么理解 Git 分支协作？" in messages[1]["content"]
        return "标题：Git 分支协作入门。"

    monkeypatch.setattr(use_cases, "acompletion", fake_completion)

    title = await use_cases._generate_session_title(
        subject="Git",
        question="怎么理解 Git 分支协作？",
        selected_text="feature/payment-integration",
        assistant_response="分支让不同任务在独立开发路径上并行推进。",
    )

    assert title == "Git 分支协作入门"


@pytest.mark.anyio
async def test_generate_session_title_falls_back_when_llm_fails(monkeypatch):
    async def fake_completion(_messages, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(use_cases, "acompletion", fake_completion)
    question = "这是一段很长很长的问题内容，用来确认标题失败时会回退到本地标题"

    title = await use_cases._generate_session_title(
        subject="Git",
        question=question,
        selected_text=None,
        assistant_response="",
    )

    assert title == use_cases._build_session_title(question)
