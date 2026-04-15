from __future__ import annotations

from app.shared.infra.llm_support.context_window import ContextWindowManager, TokenBudget
from app.shared.infra.strategies import StrategyMode
from app.workflows.interact.prompts.messages import build_chat_messages
from app.workflows.interact.support.types import RecentMessage


def test_build_context_reuses_unused_history_budget_for_retrieval() -> None:
    manager = ContextWindowManager(
        TokenBudget(
            total=1200,
            system_prompt=120,
            retrieval_context=80,
            chat_history=500,
            user_query=60,
            reserved_for_output=100,
        )
    )

    system_prompt = "你是一个耐心的老师。" * 20
    retrieval_chunks = ["知识点A " * 120, "知识点B " * 120]

    messages = manager.build_context(
        system_prompt=system_prompt,
        retrieval_chunks=retrieval_chunks,
        chat_history=[],
        user_query="帮我解释这个知识点",
    )

    system_message = messages[0]["content"]

    # 如果仍然是硬上限裁切，这里通常只会保留很短的 retrieval 文本。
    assert "参考资料：" in system_message
    assert system_message.count("知识点A") > 20


def test_truncate_messages_keeps_truncated_latest_message() -> None:
    manager = ContextWindowManager()
    messages = [
        {
            "role": "user",
            "content": "很长的消息内容 " * 300,
        }
    ]

    truncated = manager.truncate_messages(messages, max_tokens=30)

    assert len(truncated) == 1
    assert truncated[0]["role"] == "user"
    assert truncated[0]["content"].endswith("...")


def test_build_chat_messages_defers_history_truncation_to_soft_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.workflows.interact.prompts.messages.populate_prompt",
        lambda *args, **kwargs: "sys",
    )
    monkeypatch.setattr(
        "app.workflows.interact.prompts.messages.get_strategy_instruction",
        lambda mode: mode.value,
    )

    manager = ContextWindowManager(
        TokenBudget(
            total=260,
            system_prompt=20,
            retrieval_context=20,
            chat_history=40,
            user_query=20,
            reserved_for_output=20,
        )
    )
    recent_messages = [
        RecentMessage(role="user", content="A" * 60),
        RecentMessage(role="assistant", content="B" * 60),
        RecentMessage(role="user", content="C" * 60),
    ]

    messages = build_chat_messages(
        subject="demo",
        strategy_mode=StrategyMode.GUIDED,
        retrieval_results=[],
        recent_messages=recent_messages,
        weak_points=[],
        recent_mistakes=[],
        question="最后问题",
        context_window=manager,
    )

    history_messages = messages[1:-1]

    assert len(history_messages) == 3
    assert [item["role"] for item in history_messages] == ["user", "assistant", "user"]
