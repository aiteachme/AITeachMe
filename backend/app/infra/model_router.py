"""按任务类型的模型路由。

不同 AI 任务（抽取、出题、判卷、对话……）可以使用不同的模型和参数。
路由逻辑：config 中 model_overrides 覆盖 > 默认 TaskProfile > 全局 settings。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.infra.config import get_settings


class TaskType(str, Enum):
    """任务类型枚举。"""

    EXTRACT = "extract"          # Digest 抽取（需要精确）
    GENERATE = "generate"        # Examine 出题（需要创造力）
    GRADE = "grade"              # Examine 判卷
    CHAT = "chat"                # Interact 对话
    SUMMARIZE = "summarize"      # Profile 报告
    CLASSIFY = "classify"        # Ingest 分类
    VISION = "vision"            # Ingest 视觉解析
    REASONING = "reasoning"      # 深度推理任务
    DOCGEN = "docgen"            # DocGen 章节撰写与目录规划
    DOCGEN_LIGHT = "docgen_light"  # DocGen 清洗、标签提取等轻量任务
    DEFAULT = "default"          # 兜底


@dataclass(frozen=True)
class TaskProfile:
    """一类 AI 任务的模型配置。"""

    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    timeout_s: int = 60
    max_retries: int = 3


# ── 默认 profile 表 ────────────────────────────────────────────

_DEFAULT_PROFILES: dict[TaskType, TaskProfile] = {
    TaskType.EXTRACT: TaskProfile(model="", temperature=0.1, timeout_s=90),
    TaskType.GENERATE: TaskProfile(model="", temperature=0.8, timeout_s=90),
    TaskType.GRADE: TaskProfile(model="", temperature=0.1, timeout_s=60),
    TaskType.CHAT: TaskProfile(model="", temperature=0.7, timeout_s=60),
    TaskType.SUMMARIZE: TaskProfile(model="", temperature=0.5, timeout_s=60),
    TaskType.CLASSIFY: TaskProfile(model="", temperature=0.1, timeout_s=30),
    TaskType.VISION: TaskProfile(model="", temperature=0.3, timeout_s=120),
    TaskType.REASONING: TaskProfile(model="", temperature=0.2, timeout_s=120, max_retries=2),
    TaskType.DOCGEN: TaskProfile(model="", temperature=0.5, timeout_s=120, max_retries=1),
    TaskType.DOCGEN_LIGHT: TaskProfile(model="", temperature=0.1, timeout_s=60, max_retries=2),
    TaskType.DEFAULT: TaskProfile(model=""),
}


def get_task_profile(task_type: TaskType = TaskType.DEFAULT) -> TaskProfile:
    """返回指定任务类型的模型配置。

    优先级：config.model_overrides[task_type] > 默认 profile > 全局 settings。
    """

    settings = get_settings()
    base = _DEFAULT_PROFILES.get(task_type, _DEFAULT_PROFILES[TaskType.DEFAULT])

    # 如果 base.model 为空，用全局 settings 兜底
    fallback_model = settings.llm_model

    # 尝试 config override
    override_model = settings.model_overrides.get(task_type.value)

    # 尝试分级模型配置
    if not override_model:
        if task_type in (TaskType.DOCGEN_LIGHT,) and settings.llm_model_light:
            override_model = settings.llm_model_light
        elif task_type == TaskType.EXTRACT and settings.llm_model_extract:
            override_model = settings.llm_model_extract

    resolved_model = override_model or base.model or fallback_model

    return TaskProfile(
        model=resolved_model,
        temperature=base.temperature,
        max_tokens=base.max_tokens,
        timeout_s=base.timeout_s,
        max_retries=base.max_retries,
    )
