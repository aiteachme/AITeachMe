"""上下文窗口管理与 Token 预算分配。"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.shared.infra.config import get_settings

logger = structlog.get_logger()

# 粗略的 token 估算系数（中英混合约 1.5 字符 / token）
_CHARS_PER_TOKEN = 1.5


@dataclass
class TokenBudget:
    """Token 预算分配，各部分的 token 上限。"""

    total: int = 4000
    system_prompt: int = 800
    retrieval_context: int = 1500
    chat_history: int = 1000
    user_query: int = 500
    reserved_for_output: int = 200


class ContextWindowManager:
    """管理上下文窗口，确保不超预算。"""

    def __init__(self, budget: TokenBudget | None = None) -> None:
        if budget is None:
            settings = get_settings()
            budget = TokenBudget(total=settings.default_token_budget)
        self._budget = budget

    @property
    def budget(self) -> TokenBudget:
        return self._budget

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """快速估算 token 数量。"""

        return max(1, int(len(text) / _CHARS_PER_TOKEN))

    def truncate_text(self, text: str, max_tokens: int) -> str:
        """按 token 预算截断文本。"""

        estimated = self.estimate_tokens(text)
        if estimated <= max_tokens:
            return text

        max_chars = int(max_tokens * _CHARS_PER_TOKEN)
        return text[:max_chars] + "..."

    def truncate_messages(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> list[dict]:
        """按预算截断消息列表（保留最后 N 条）。"""

        if not messages:
            return messages

        total = sum(self.estimate_tokens(str(m.get("content", ""))) for m in messages)
        if total <= max_tokens:
            return messages

        result: list[dict] = []
        accumulated = 0
        for msg in reversed(messages):
            msg_tokens = self.estimate_tokens(str(msg.get("content", "")))
            if accumulated + msg_tokens > max_tokens:
                break
            result.insert(0, msg)
            accumulated += msg_tokens

        logger.debug(
            "messages_truncated",
            original_count=len(messages),
            kept_count=len(result),
            token_budget=max_tokens,
        )
        return result

    def build_context(
        self,
        *,
        system_prompt: str,
        retrieval_chunks: list[str] | None = None,
        chat_history: list[dict] | None = None,
        user_query: str,
    ) -> list[dict]:
        """按预算智能组装最终上下文。

        返回 LLM 可直接消费的 messages 列表。
        """

        budget = self._budget
        messages: list[dict] = []

        truncated_system = self.truncate_text(system_prompt, budget.system_prompt)
        messages.append({"role": "system", "content": truncated_system})

        if retrieval_chunks:
            context_text = "\n\n".join(retrieval_chunks)
            truncated_context = self.truncate_text(context_text, budget.retrieval_context)
            messages[0]["content"] += f"\n\n参考资料：\n{truncated_context}"

        if chat_history:
            truncated_history = self.truncate_messages(chat_history, budget.chat_history)
            messages.extend(truncated_history)

        truncated_query = self.truncate_text(user_query, budget.user_query)
        messages.append({"role": "user", "content": truncated_query})

        total_tokens = sum(self.estimate_tokens(str(m.get("content", ""))) for m in messages)
        logger.debug(
            "context_built",
            message_count=len(messages),
            estimated_tokens=total_tokens,
            budget_total=budget.total,
        )
        return messages


__all__ = ["ContextWindowManager", "TokenBudget"]
