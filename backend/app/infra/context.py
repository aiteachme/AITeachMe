"""教学上下文组装器 — 自动拼装 LLM 教学上下文。

把"知识快照 + 用户画像 + 相关记忆 + 检索片段 + 可用工具"
一站式组装为 LLM messages 列表。

对外使用::

    from app.infra.context import build_teaching_context

    ctx = await build_teaching_context(
        subject_id="linear-algebra",
        user_id="u1",
        user_message="什么是特征值？",
    )
    messages = ctx.to_messages()
    # 直接传给 acompletion / run_agent_loop
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

from app.infra.memory import get_user_profile, load_doc_to_context, recall
from app.infra.search import search_knowledge

logger = structlog.get_logger()


@dataclass
class TeachingContext:
    """组装好的教学上下文。

    Attributes:
        system_prompt: 系统提示词（教学角色定义）。
        profile_message: 用户画像消息。
        knowledge_message: 检索到的知识片段。
        memory_message: 相关历史记忆。
        tool_names: 可用工具名列表。
        user_message: 用户原始消息。
        extra_messages: 额外注入的消息。
    """

    system_prompt: str = ""
    profile_message: str = ""
    knowledge_message: str = ""
    memory_message: str = ""
    tool_names: list[str] = field(default_factory=list)
    user_message: str = ""
    extra_messages: list[dict] = field(default_factory=list)

    def to_messages(self) -> list[dict]:
        """转为 LLM messages 列表（自动跳过空内容）。"""

        messages: list[dict] = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if self.profile_message:
            messages.append({"role": "system", "content": self.profile_message})
        if self.knowledge_message:
            messages.append({"role": "system", "content": self.knowledge_message})
        if self.memory_message:
            messages.append({"role": "system", "content": self.memory_message})
        for msg in self.extra_messages:
            messages.append(msg)
        if self.user_message:
            messages.append({"role": "user", "content": self.user_message})

        return messages


# ── 默认系统提示词 ────────────────────────────────────────────

_DEFAULT_SYSTEM_PROMPT = """你是 AITeachMe 教学助手，一位有耐心、善于引导的教师。

教学原则：
- 用苏格拉底式追问引导学生主动思考，而非直接给答案
- 优先使用类比和生活化例子解释抽象概念
- 关注学生的薄弱点，有针对性地讲解
- 回答使用中文，除非学生用其他语言提问
- 适时检查学生是否真正理解（追问或出小测验）

如果有知识片段参考，请基于参考内容回答，并标注来源。
如果有用户画像信息，请据此调整讲解风格和深度。
"""


async def build_teaching_context(
    *,
    user_message: str,
    subject_id: str = "",
    user_id: str = "default",
    system_prompt: str = "",
    include_profile: bool = True,
    include_knowledge: bool = True,
    include_memory: bool = True,
    knowledge_top_k: int = 3,
    memory_top_k: int = 5,
    tool_names: list[str] | None = None,
    chat_history: list[dict] | None = None,
) -> TeachingContext:
    """一站式组装教学上下文。

    自动完成：用户画像加载 → 知识库检索 → 记忆回忆 → 组装。
    外部只需传核心参数，所有中间步骤内部处理。

    Args:
        user_message: 用户当前消息。
        subject_id: 学科标识（用于知识检索）。
        user_id: 用户标识（用于画像和记忆）。
        system_prompt: 自定义系统提示词（不传则用默认教学提示词）。
        include_profile: 是否加载用户画像。
        include_knowledge: 是否检索知识库。
        include_memory: 是否回忆相关记忆。
        knowledge_top_k: 知识检索数量。
        memory_top_k: 记忆回忆数量。
        tool_names: 可用工具列表。
        chat_history: 对话历史。

    Returns:
        TeachingContext — 调用 ``.to_messages()`` 获取 LLM 消息列表。

    Example::

        ctx = await build_teaching_context(
            user_message="什么是特征值？",
            subject_id="linear-algebra",
            user_id="u1",
        )
        messages = ctx.to_messages()
        result = await acompletion(messages)
    """

    ctx = TeachingContext(
        system_prompt=system_prompt or _DEFAULT_SYSTEM_PROMPT,
        user_message=user_message,
        tool_names=tool_names or [],
    )

    # 1. 用户画像
    if include_profile:
        try:
            profile, learner_doc = await asyncio.gather(
                get_user_profile(user_id),
                load_doc_to_context(user_id),
            )
            msg = profile.to_system_message()
            profile_blocks = [
                str(msg.get("content", "")).strip(),
                ("## LEARNER.md\n" + learner_doc.strip()) if learner_doc.strip() else "",
            ]
            ctx.profile_message = "\n\n".join(block for block in profile_blocks if block)
        except Exception as exc:
            logger.debug("context_profile_skipped", error=str(exc))

    # 2. 知识库检索
    if include_knowledge and subject_id:
        try:
            chunks = await search_knowledge(
                user_message, subject_id, top_k=knowledge_top_k,
            )
            if chunks:
                lines = ["## 参考知识片段\n"]
                for i, c in enumerate(chunks, 1):
                    title = getattr(c, "title", "") or f"片段{i}"
                    content = getattr(c, "content", str(c))
                    lines.append(f"### [{i}] {title}\n{content}\n")
                ctx.knowledge_message = "\n".join(lines)
        except Exception as exc:
            logger.debug("context_knowledge_skipped", error=str(exc))

    # 3. 记忆回忆
    if include_memory:
        try:
            entries = await recall(user_message, user_id=user_id, top_k=memory_top_k)
            if entries:
                lines = ["## 历史记忆\n"]
                for e in entries:
                    lines.append(f"- [{e.tag}] {e.content}")
                ctx.memory_message = "\n".join(lines)
        except Exception as exc:
            logger.debug("context_memory_skipped", error=str(exc))

    # 4. 对话历史
    if chat_history:
        ctx.extra_messages = list(chat_history)

    logger.info("teaching_context_built",
                user_id=user_id,
                subject=subject_id,
                has_profile=bool(ctx.profile_message),
                has_knowledge=bool(ctx.knowledge_message),
                has_memory=bool(ctx.memory_message),
                tool_count=len(ctx.tool_names))

    return ctx
