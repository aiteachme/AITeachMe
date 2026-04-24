"""上下文窗口管理与 Token 预算分配。"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.shared.infra.llm_support.defaults import DEFAULT_LLM_TOKEN_BUDGET

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

    @property
    def input_budget(self) -> int:
        """预算给输入消息的 token 总量。"""

        return max(1, self.total - self.reserved_for_output)


class ContextWindowManager:
    """管理上下文窗口，确保不超预算。"""

    def __init__(self, budget: TokenBudget | None = None) -> None:
        if budget is None:
            budget = TokenBudget(total=DEFAULT_LLM_TOKEN_BUDGET)
        self._budget = budget

    @property
    def budget(self) -> TokenBudget:
        return self._budget

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """快速估算 token 数量。"""

        normalized = str(text or "")
        if not normalized.strip():
            return 0
        return max(1, int(len(normalized) / _CHARS_PER_TOKEN))

    def estimate_message_tokens(self, messages: list[dict]) -> int:
        """估算消息列表的 token 数量。"""

        return sum(self.estimate_tokens(str(message.get("content") or "")) for message in messages)

    def truncate_text(self, text: str, max_tokens: int) -> str:
        """按 token 预算截断文本。"""

        normalized = str(text or "")
        if max_tokens <= 0 or not normalized.strip():
            return ""

        estimated = self.estimate_tokens(normalized)
        if estimated <= max_tokens:
            return normalized

        max_chars = max(1, int(max_tokens * _CHARS_PER_TOKEN))
        if max_chars >= len(normalized):
            return normalized
        if max_chars <= 3:
            return normalized[:max_chars]
        return normalized[: max_chars - 3].rstrip() + "..."

    def truncate_messages(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> list[dict]:
        """按预算截断消息列表（保留最后 N 条）。"""

        if not messages:
            return messages

        total = self.estimate_message_tokens(messages)
        if total <= max_tokens:
            return messages

        result: list[dict] = []
        accumulated = 0
        for msg in reversed(messages):
            msg_tokens = self.estimate_tokens(str(msg.get("content", "")))
            if accumulated + msg_tokens > max_tokens:
                if not result and max_tokens > 0:
                    truncated = dict(msg)
                    truncated["content"] = self.truncate_text(
                        str(msg.get("content", "")),
                        max_tokens,
                    )
                    result.insert(0, truncated)
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

    def _allocate_section_budgets(
        self,
        *,
        system_prompt: str,
        retrieval_text: str,
        chat_history: list[dict],
        user_query: str,
    ) -> dict[str, int]:
        """在总输入预算内做软分配，而不是把每段卡死在静态上限。"""

        budget = self._budget
        estimates = {
            "system": self.estimate_tokens(system_prompt) if system_prompt.strip() else 0,
            "retrieval": self.estimate_tokens(retrieval_text) if retrieval_text.strip() else 0,
            "history": self.estimate_message_tokens(chat_history) if chat_history else 0,
            "user": self.estimate_tokens(user_query) if user_query.strip() else 0,
        }
        caps = {
            "system": budget.system_prompt,
            "retrieval": budget.retrieval_context,
            "history": budget.chat_history,
            "user": budget.user_query,
        }
        allocations = {
            name: min(estimates[name], caps[name], budget.input_budget)
            for name in estimates
        }
        headroom = max(0, budget.input_budget - sum(allocations.values()))
        for name in ("user", "retrieval", "history", "system"):
            if headroom <= 0:
                break
            unmet = max(0, estimates[name] - allocations[name])
            if unmet <= 0:
                continue
            borrowed = min(headroom, unmet)
            allocations[name] += borrowed
            headroom -= borrowed

        logger.debug(
            "context_budget_allocated",
            estimates=estimates,
            allocations=allocations,
            input_budget=budget.input_budget,
            reserved_for_output=budget.reserved_for_output,
        )
        return allocations

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
        retrieval_text = "\n\n".join(retrieval_chunks or [])
        allocations = self._allocate_section_budgets(
            system_prompt=system_prompt,
            retrieval_text=retrieval_text,
            chat_history=chat_history or [],
            user_query=user_query,
        )

        truncated_system = self.truncate_text(system_prompt, allocations["system"])
        messages.append({"role": "system", "content": truncated_system})

        if retrieval_text:
            truncated_context = self.truncate_text(
                retrieval_text,
                allocations["retrieval"],
            )
            messages[0]["content"] += f"\n\n参考资料：\n{truncated_context}"

        if chat_history:
            truncated_history = self.truncate_messages(
                chat_history,
                allocations["history"],
            )
            messages.extend(truncated_history)

        messages[0]["content"] = self.truncate_text(
            messages[0]["content"],
            allocations["system"] + allocations["retrieval"],
        )

        truncated_query = self.truncate_text(user_query, allocations["user"])
        messages.append({"role": "user", "content": truncated_query})

        total_tokens = self.estimate_message_tokens(messages)
        logger.debug(
            "context_built",
            message_count=len(messages),
            estimated_tokens=total_tokens,
            budget_total=budget.total,
            input_budget=budget.input_budget,
        )
        return messages


__all__ = ["ContextWindowManager", "TokenBudget"]
