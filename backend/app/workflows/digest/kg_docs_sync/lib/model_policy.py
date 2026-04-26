"""Central model policy for KG docs-sync LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.digest.common.model_policy import compact_metadata

KGDocsSyncModelSlot = Literal["light", "primary"]


class KGDocsSyncModelStep(str, Enum):
    QUESTION_CONCEPTS = "kg_docs_sync.question_concepts"
    SECTION_GRAPH = "kg_docs_sync.section_graph"
    EMPTY_REPAIR = "kg_docs_sync.empty_repair"


@dataclass(frozen=True)
class KGDocsSyncModelPolicy:
    step: KGDocsSyncModelStep
    call_type: Literal["structured"]
    call_purpose: LLMCallPurpose
    model: KGDocsSyncModelSlot
    max_tokens: int | None = None
    temperature_override: float | None = None
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        """Return kwargs shared by KG docs-sync structured call sites."""

        kwargs: dict[str, object] = {
            "call_purpose": self.call_purpose,
            "model": self.model,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.temperature_override is not None:
            kwargs["temperature"] = self.temperature_override
        return kwargs

    def metadata(self) -> dict[str, object]:
        """Return stable observability metadata for one KG docs-sync model call."""

        return {
            "kg_docs_sync_model_step": self.step.value,
            "kg_docs_sync_model_slot": self.model,
            "kg_docs_sync_call_type": self.call_type,
        }

    def completion_kwargs_with_metadata(
        self,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(extra_metadata, metadata, self.metadata())
        return kwargs


_POLICIES: dict[KGDocsSyncModelStep, KGDocsSyncModelPolicy] = {
    KGDocsSyncModelStep.QUESTION_CONCEPTS: KGDocsSyncModelPolicy(
        step=KGDocsSyncModelStep.QUESTION_CONCEPTS,
        call_type="structured",
        call_purpose=LLMCallPurpose.DOCGEN_LIGHT,
        model="light",
        max_tokens=700,
        note="题目 fallback 的轻量概念识别，只提取少量概念/方法。",
    ),
    KGDocsSyncModelStep.SECTION_GRAPH: KGDocsSyncModelPolicy(
        step=KGDocsSyncModelStep.SECTION_GRAPH,
        call_type="structured",
        call_purpose=LLMCallPurpose.EXTRACT,
        model="light",
        max_tokens=2600,
        note="从单个知识文档章节抽取候选知识单元和关系，用 EXTRACT profile + light 模型层级。",
    ),
    KGDocsSyncModelStep.EMPTY_REPAIR: KGDocsSyncModelPolicy(
        step=KGDocsSyncModelStep.EMPTY_REPAIR,
        call_type="structured",
        call_purpose=LLMCallPurpose.EXTRACT,
        model="light",
        max_tokens=1200,
        note="主抽取为空时的极短修复抽取，只补明显漏掉的知识点。",
    ),
}


def get_kg_docs_sync_model_policy(step: KGDocsSyncModelStep | str) -> KGDocsSyncModelPolicy:
    resolved_step = step if isinstance(step, KGDocsSyncModelStep) else KGDocsSyncModelStep(str(step))
    return _POLICIES[resolved_step]


def kg_docs_sync_completion_kwargs(step: KGDocsSyncModelStep | str) -> dict[str, object]:
    return get_kg_docs_sync_model_policy(step).completion_kwargs()


def kg_docs_sync_completion_kwargs_with_metadata(
    step: KGDocsSyncModelStep | str,
    *,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_kg_docs_sync_model_policy(step).completion_kwargs_with_metadata(
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "KGDocsSyncModelPolicy",
    "KGDocsSyncModelSlot",
    "KGDocsSyncModelStep",
    "get_kg_docs_sync_model_policy",
    "kg_docs_sync_completion_kwargs",
    "kg_docs_sync_completion_kwargs_with_metadata",
]
