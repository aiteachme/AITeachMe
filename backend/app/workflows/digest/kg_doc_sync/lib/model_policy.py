"""Central model policy for KG docs-sync LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.shared.infra.settings import get_settings
from app.workflows.common.model_policy import ProviderNativeToolPolicy, compact_metadata

KGDocSyncModelSlot = Literal["light", "primary", "reason"]

_SECTION_GRAPH_TIMEOUT_S = 300
_SECTION_GRAPH_MAX_CONTENT_CHARS = 60000
_SECTION_GRAPH_COURSE_CONTEXT_MAX_CHARS = 2400


class KGDocSyncModelStep(str, Enum):
    SECTION_GRAPH = "kg_doc_sync.section_graph"
    EMPTY_REPAIR = "kg_doc_sync.empty_repair"


@dataclass(frozen=True)
class KGDocSyncModelPolicy:
    step: KGDocSyncModelStep
    call_type: Literal["structured"]
    model: KGDocSyncModelSlot
    max_tokens: int | None = None
    timeout_s: int | None = None
    max_retries: int = 3
    max_content_chars: int | None = None
    course_context_max_chars: int | None = None
    temperature: float | None = None
    provider_native_tools: ProviderNativeToolPolicy = field(default_factory=ProviderNativeToolPolicy.disabled)
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        """Return kwargs shared by KG docs-sync structured call sites."""

        kwargs: dict[str, object] = {
            "model": self.model,
            PROVIDER_NATIVE_TOOLS_KWARG: self.provider_native_tools.build(
                settings=get_settings(),
                web_search=False,
                file_search=False,
            ),
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        kwargs["max_retries"] = self.max_retries
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def metadata(self) -> dict[str, object]:
        """Return stable observability metadata for one KG docs-sync model call."""

        return {
            "kg_doc_sync_model_step": self.step.value,
            "kg_doc_sync_model_slot": self.model,
            "kg_doc_sync_call_type": self.call_type,
            "kg_doc_sync_max_tokens": self.max_tokens,
            "kg_doc_sync_timeout_s": self.timeout_s,
            "kg_doc_sync_max_retries": self.max_retries,
            **self.provider_native_tools.metadata(prefix="kg_doc_sync_provider_native"),
        }

    def completion_kwargs_with_metadata(
        self,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(extra_metadata, metadata, self.metadata())
        return kwargs


_POLICIES: dict[KGDocSyncModelStep, KGDocSyncModelPolicy] = {
    KGDocSyncModelStep.SECTION_GRAPH: KGDocSyncModelPolicy(
        step=KGDocSyncModelStep.SECTION_GRAPH,
        call_type="structured",
        model="light",
        max_tokens=7000,
        timeout_s=_SECTION_GRAPH_TIMEOUT_S,
        max_content_chars=_SECTION_GRAPH_MAX_CONTENT_CHARS,
        course_context_max_chars=_SECTION_GRAPH_COURSE_CONTEXT_MAX_CHARS,
        temperature=0.1,
        note="从单个知识文档章节抽取高置信候选知识单元和关系；输出预算要容纳最多 12 个节点和 18 条关系的结构化 JSON。",
    ),
    KGDocSyncModelStep.EMPTY_REPAIR: KGDocSyncModelPolicy(
        step=KGDocSyncModelStep.EMPTY_REPAIR,
        call_type="structured",
        model="light",
        max_tokens=3600,
        timeout_s=_SECTION_GRAPH_TIMEOUT_S,
        temperature=0.1,
        note="主抽取为空时的极短修复抽取，只补明显漏掉的知识点。",
    ),
}


def get_kg_doc_sync_model_policy(step: KGDocSyncModelStep | str) -> KGDocSyncModelPolicy:
    resolved_step = step if isinstance(step, KGDocSyncModelStep) else KGDocSyncModelStep(str(step))
    return _POLICIES[resolved_step]


def kg_doc_sync_completion_kwargs(step: KGDocSyncModelStep | str) -> dict[str, object]:
    return get_kg_doc_sync_model_policy(step).completion_kwargs()


def kg_doc_sync_section_llm_timeout_s() -> int:
    policy = get_kg_doc_sync_model_policy(KGDocSyncModelStep.SECTION_GRAPH)
    return max(1, int(policy.timeout_s or _SECTION_GRAPH_TIMEOUT_S))


def kg_doc_sync_section_llm_max_content_chars() -> int:
    policy = get_kg_doc_sync_model_policy(KGDocSyncModelStep.SECTION_GRAPH)
    return max(1000, int(policy.max_content_chars or _SECTION_GRAPH_MAX_CONTENT_CHARS))


def kg_doc_sync_course_context_max_chars() -> int:
    policy = get_kg_doc_sync_model_policy(KGDocSyncModelStep.SECTION_GRAPH)
    return max(200, int(policy.course_context_max_chars or _SECTION_GRAPH_COURSE_CONTEXT_MAX_CHARS))


def kg_doc_sync_completion_kwargs_with_metadata(
    step: KGDocSyncModelStep | str,
    *,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_kg_doc_sync_model_policy(step).completion_kwargs_with_metadata(
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "KGDocSyncModelPolicy",
    "KGDocSyncModelSlot",
    "KGDocSyncModelStep",
    "get_kg_doc_sync_model_policy",
    "kg_doc_sync_completion_kwargs",
    "kg_doc_sync_completion_kwargs_with_metadata",
    "kg_doc_sync_course_context_max_chars",
    "kg_doc_sync_section_llm_max_content_chars",
    "kg_doc_sync_section_llm_timeout_s",
]
