"""Central model policy for exam question-build LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.common.model_policy import compact_metadata

QuestionBuildModelSlot = Literal["light", "primary", "reason"]


class QuestionBuildModelStep(str, Enum):
    FILTER_UNITS = "question_build.filter_units"
    ALLOCATE_BLUEPRINTS = "question_build.allocate_knowledge_units"
    PLAN_REQUIREMENTS = "question_build.plan_question_requirements"
    GENERATE_ONE = "question_build.generate_one"
    PLAYGROUND_BATCH = "question_build.playground"


@dataclass(frozen=True)
class QuestionBuildModelPolicy:
    step: QuestionBuildModelStep
    call_type: Literal["structured"]
    call_purpose: LLMCallPurpose
    model: QuestionBuildModelSlot
    max_tokens: int | None = None
    min_tokens: int | None = None
    tokens_per_question: int | None = None
    max_tokens_cap: int | None = None
    attempt_max_tokens: tuple[int, ...] = ()
    temperature_override: float | None = None
    note: str = ""

    def resolved_max_tokens(
        self,
        *,
        question_count: int | None = None,
        attempt: int | None = None,
    ) -> int | None:
        """Return the output-token budget for this call shape."""

        if self.attempt_max_tokens:
            index = max(0, min(int(attempt or 1) - 1, len(self.attempt_max_tokens) - 1))
            return self.attempt_max_tokens[index]
        if self.tokens_per_question is not None:
            normalized_count = max(1, int(question_count or 1))
            floor = int(self.min_tokens or 0)
            cap = int(self.max_tokens_cap or self.max_tokens or 0)
            scaled = max(floor, normalized_count * int(self.tokens_per_question))
            return min(cap, scaled) if cap > 0 else scaled
        return self.max_tokens

    def completion_kwargs(
        self,
        *,
        question_count: int | None = None,
        attempt: int | None = None,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "call_purpose": self.call_purpose,
            "model": self.model,
        }
        max_tokens = self.resolved_max_tokens(question_count=question_count, attempt=attempt)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.temperature_override is not None:
            kwargs["temperature"] = self.temperature_override
        return kwargs

    def metadata(
        self,
        *,
        question_count: int | None = None,
        attempt: int | None = None,
    ) -> dict[str, object]:
        return {
            "question_build_model_step": self.step.value,
            "question_build_model_slot": self.model,
            "question_build_call_type": self.call_type,
            "question_build_max_tokens": self.resolved_max_tokens(
                question_count=question_count,
                attempt=attempt,
            ),
        }

    def completion_kwargs_with_metadata(
        self,
        *,
        question_count: int | None = None,
        attempt: int | None = None,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs(question_count=question_count, attempt=attempt)
        kwargs["extra_metadata"] = compact_metadata(
            extra_metadata,
            metadata,
            self.metadata(question_count=question_count, attempt=attempt),
        )
        return kwargs


_POLICIES: dict[QuestionBuildModelStep, QuestionBuildModelPolicy] = {
    QuestionBuildModelStep.FILTER_UNITS: QuestionBuildModelPolicy(
        step=QuestionBuildModelStep.FILTER_UNITS,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        max_tokens=2600,
        temperature_override=0.1,
        note="知识点候选池筛选需要返回排序、理由和兜底提示，避免长图谱下 JSON 被截断。",
    ),
    QuestionBuildModelStep.ALLOCATE_BLUEPRINTS: QuestionBuildModelPolicy(
        step=QuestionBuildModelStep.ALLOCATE_BLUEPRINTS,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        min_tokens=3200,
        tokens_per_question=520,
        max_tokens_cap=12000,
        temperature_override=0.45,
        note="按题量线性扩容，覆盖题型、难度和知识点分配。",
    ),
    QuestionBuildModelStep.PLAN_REQUIREMENTS: QuestionBuildModelPolicy(
        step=QuestionBuildModelStep.PLAN_REQUIREMENTS,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        min_tokens=1800,
        tokens_per_question=280,
        max_tokens_cap=9000,
        temperature_override=0.2,
        note="用户约束拆成逐题生成要求，按题量扩容。",
    ),
    QuestionBuildModelStep.GENERATE_ONE: QuestionBuildModelPolicy(
        step=QuestionBuildModelStep.GENERATE_ONE,
        call_type="structured",
        call_purpose=LLMCallPurpose.GENERATE,
        model="reason",
        attempt_max_tokens=(4200, 6200),
        temperature_override=0.65,
        note="单题生成第二次重试给更大的结构化输出空间。",
    ),
    QuestionBuildModelStep.PLAYGROUND_BATCH: QuestionBuildModelPolicy(
        step=QuestionBuildModelStep.PLAYGROUND_BATCH,
        call_type="structured",
        call_purpose=LLMCallPurpose.GENERATE,
        model="reason",
        min_tokens=4800,
        tokens_per_question=720,
        max_tokens_cap=12000,
        temperature_override=0.65,
        note="兼容脚本批量出题，按题数扩容。",
    ),
}


def get_question_build_model_policy(
    step: QuestionBuildModelStep | str,
) -> QuestionBuildModelPolicy:
    resolved_step = step if isinstance(step, QuestionBuildModelStep) else QuestionBuildModelStep(str(step))
    return _POLICIES[resolved_step]


def question_build_completion_kwargs(
    step: QuestionBuildModelStep | str,
    *,
    question_count: int | None = None,
    attempt: int | None = None,
) -> dict[str, object]:
    return get_question_build_model_policy(step).completion_kwargs(
        question_count=question_count,
        attempt=attempt,
    )


def question_build_completion_kwargs_with_metadata(
    step: QuestionBuildModelStep | str,
    *,
    question_count: int | None = None,
    attempt: int | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_question_build_model_policy(step).completion_kwargs_with_metadata(
        question_count=question_count,
        attempt=attempt,
        extra_metadata=extra_metadata,
        **metadata,
    )


def question_build_attempt_max_tokens(step: QuestionBuildModelStep | str) -> tuple[int, ...]:
    return tuple(get_question_build_model_policy(step).attempt_max_tokens)


__all__ = [
    "QuestionBuildModelPolicy",
    "QuestionBuildModelSlot",
    "QuestionBuildModelStep",
    "get_question_build_model_policy",
    "question_build_attempt_max_tokens",
    "question_build_completion_kwargs",
    "question_build_completion_kwargs_with_metadata",
]

