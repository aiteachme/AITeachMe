"""Model policy for the independent multimodal DocGen lane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.workflows.common.model_policy import compact_metadata


class MultimodalDocGenModelStep(str, Enum):
    VISUAL_EVIDENCE = "prepare_visual_evidence.understand_images"


@dataclass(frozen=True)
class MultimodalDocGenModelPolicy:
    step: MultimodalDocGenModelStep
    call_type: Literal["structured"]
    model: str
    max_tokens: int
    timeout_s: int
    overall_timeout_s: int
    max_retries: int
    temperature: float

    def completion_kwargs_with_metadata(
        self,
        *,
        model_name: str | None = None,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        resolved_model = str(model_name or self.model).strip() or self.model
        stable_metadata = {
            "docgen_multimodal_model_step": self.step.value,
            "docgen_multimodal_model_slot": "light",
            "docgen_multimodal_model_name": resolved_model,
            "docgen_multimodal_call_type": self.call_type,
            "docgen_multimodal_timeout_s": self.timeout_s,
            "docgen_multimodal_overall_timeout_s": self.overall_timeout_s,
            "docgen_multimodal_max_retries": self.max_retries,
        }
        return {
            "model": resolved_model,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout_s,
            "overall_timeout_s": self.overall_timeout_s,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            # The current compatible gateway has already been verified with
            # multimodal Chat Completions. Keeping the shape explicit avoids
            # passing Chat image blocks unchanged into Responses input.
            "api_mode": "chat_completions",
            "extra_metadata": compact_metadata(
                extra_metadata,
                metadata,
                stable_metadata,
            ),
        }


_VISUAL_EVIDENCE_POLICY = MultimodalDocGenModelPolicy(
    step=MultimodalDocGenModelStep.VISUAL_EVIDENCE,
    call_type="structured",
    model="light",
    max_tokens=5200,
    timeout_s=120,
    overall_timeout_s=180,
    max_retries=3,
    temperature=0.1,
)


def multimodal_docgen_completion_kwargs_with_metadata(
    step: MultimodalDocGenModelStep | str,
    *,
    model_name: str | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    resolved = step if isinstance(step, MultimodalDocGenModelStep) else MultimodalDocGenModelStep(str(step))
    if resolved != MultimodalDocGenModelStep.VISUAL_EVIDENCE:
        raise ValueError(f"unsupported multimodal DocGen model step: {resolved}")
    return _VISUAL_EVIDENCE_POLICY.completion_kwargs_with_metadata(
        model_name=model_name,
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "MultimodalDocGenModelPolicy",
    "MultimodalDocGenModelStep",
    "multimodal_docgen_completion_kwargs_with_metadata",
]
