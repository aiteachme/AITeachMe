"""用户画像 — 汇聚各维度的用户认知信息。

对外使用::

    from app.shared.infra.memory import get_user_profile
    profile = await get_user_profile("u123")
    msg = profile.to_system_message()  # 直接注入 LLM 上下文
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.shared.infra.memory.types import MemoryEntry, MemoryTag


@dataclass
class UserProfile:
    """用户画像 — 从记忆条目自动构建。

    Attributes:
        user_id: 用户标识。
        background: 用户背景信息（"大三计算机专业"）。
        learning_style: 偏好的学习方式（"喜欢类比解释"）。
        preferences: 其他学习偏好列表。
        strengths: 擅长的知识领域。
        weaknesses: 薄弱的知识领域。
        insights: 教学洞察（系统对用户的理解）。
        recent_topics: 最近学习的主题。
        last_active: 最后活跃时间。
    """

    user_id: str
    background: str = ""
    learning_style: str = ""
    preferences: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    last_active: datetime | None = None

    def to_system_message(self) -> dict:
        """转换为 LLM system message，直接注入上下文。

        Returns:
            一个 ``{"role": "system", "content": "..."}`` 字典。
            如果画像为空，返回空内容的 message（不影响上下文）。

        Example::

            profile = await get_user_profile("u1")
            messages = [profile.to_system_message()] + other_messages
            answer = await acompletion(messages)
        """

        lines = ["## 关于当前学生"]
        has_info = False

        if self.background:
            lines.append(f"- 背景：{self.background}")
            has_info = True
        if self.learning_style:
            lines.append(f"- 偏好学习方式：{self.learning_style}")
            has_info = True
        if self.preferences:
            lines.append(f"- 学习偏好：{'、'.join(self.preferences[:5])}")
            has_info = True
        if self.strengths:
            lines.append(f"- 较强领域：{'、'.join(self.strengths[:5])}")
            has_info = True
        if self.weaknesses:
            lines.append(f"- 薄弱领域：{'、'.join(self.weaknesses[:5])}")
            has_info = True
        if self.insights:
            lines.append(f"- 教学备注：{'；'.join(self.insights[:3])}")
            has_info = True
        if self.recent_topics:
            lines.append(f"- 近期学习：{'、'.join(self.recent_topics[-5:])}")
            has_info = True

        content = "\n".join(lines) if has_info else ""
        return {"role": "system", "content": content}

    def to_summary(self) -> str:
        """生成一段简要自然语言摘要。"""

        parts = []
        if self.background:
            parts.append(self.background)
        if self.learning_style:
            parts.append(f"学习风格偏好{self.learning_style}")
        if self.strengths:
            parts.append(f"擅长{'、'.join(self.strengths[:3])}")
        if self.weaknesses:
            parts.append(f"薄弱点{'、'.join(self.weaknesses[:3])}")
        return "，".join(parts) if parts else "暂无画像信息"

    @staticmethod
    def build_from_memories(user_id: str, memories: list[MemoryEntry]) -> UserProfile:
        """从记忆条目列表构建用户画像。

        根据 tag 分类汇总，自动提取各维度信息。
        """

        profile = UserProfile(user_id=user_id)
        latest_time: datetime | None = None

        for entry in memories:
            tag = entry.tag
            content = entry.content.strip()

            if tag == MemoryTag.BACKGROUND:
                # 背景信息取最新的（或拼接）
                if not profile.background:
                    profile.background = content
                else:
                    profile.background = f"{profile.background}；{content}"

            elif tag == MemoryTag.PREFERENCE:
                if "学习方式" in content or "偏好" in content or "风格" in content:
                    profile.learning_style = content
                else:
                    profile.preferences.append(content)

            elif tag == MemoryTag.STRENGTH:
                profile.strengths.append(content)

            elif tag == MemoryTag.WEAKNESS:
                profile.weaknesses.append(content)

            elif tag == MemoryTag.INSIGHT:
                profile.insights.append(content)

            elif tag == MemoryTag.NOTE:
                profile.recent_topics.append(content)

            # 跟踪最后活跃时间
            if latest_time is None or entry.updated_at > latest_time:
                latest_time = entry.updated_at

        profile.last_active = latest_time

        # 去重
        profile.strengths = list(dict.fromkeys(profile.strengths))
        profile.weaknesses = list(dict.fromkeys(profile.weaknesses))
        profile.preferences = list(dict.fromkeys(profile.preferences))
        profile.insights = list(dict.fromkeys(profile.insights))

        return profile
