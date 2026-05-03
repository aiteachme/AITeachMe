"""Central model policy for ingest parsing LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.common.model_policy import compact_metadata

IngestParsingModelSlot = Literal["vision", "ocr"]


class IngestParsingModelStep(str, Enum):
    IMAGE_TO_MARKDOWN = "ingest.parsing.image_to_markdown"


@dataclass(frozen=True)
class IngestParsingModelPolicy:
    step: IngestParsingModelStep
    call_type: Literal["vision"]
    call_purpose: LLMCallPurpose
    model: IngestParsingModelSlot | None
    max_tokens: int
    temperature_override: float | None = None
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "call_purpose": self.call_purpose,
            "max_tokens": self.max_tokens,
        }
        if self.temperature_override is not None:
            kwargs["temperature"] = self.temperature_override
        return kwargs

    def completion_kwargs_with_metadata(
        self,
        *,
        model_selector: str | None = None,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(
            extra_metadata,
            metadata,
            {
                "ingest_model_step": self.step.value,
                "ingest_model_slot": model_selector or self.model or "",
                "ingest_call_type": self.call_type,
                "ingest_max_tokens": self.max_tokens,
            },
        )
        return kwargs


_POLICIES: dict[IngestParsingModelStep, IngestParsingModelPolicy] = {
    IngestParsingModelStep.IMAGE_TO_MARKDOWN: IngestParsingModelPolicy(
        step=IngestParsingModelStep.IMAGE_TO_MARKDOWN,
        call_type="vision",
        call_purpose=LLMCallPurpose.VISION,
        model=None,
        max_tokens=6000,
        temperature_override=0.3,
        note="单页图片 OCR 需要保留公式、表格和标题层级，输出预算不依赖 provider 默认值。",
    ),
}


def get_ingest_parsing_model_policy(
    step: IngestParsingModelStep | str,
) -> IngestParsingModelPolicy:
    resolved_step = step if isinstance(step, IngestParsingModelStep) else IngestParsingModelStep(str(step))
    return _POLICIES[resolved_step]


def ingest_parsing_completion_kwargs_with_metadata(
    step: IngestParsingModelStep | str,
    *,
    model_selector: str | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_ingest_parsing_model_policy(step).completion_kwargs_with_metadata(
        model_selector=model_selector,
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "IngestParsingModelPolicy",
    "IngestParsingModelSlot",
    "IngestParsingModelStep",
    "get_ingest_parsing_model_policy",
    "ingest_parsing_completion_kwargs_with_metadata",
]

