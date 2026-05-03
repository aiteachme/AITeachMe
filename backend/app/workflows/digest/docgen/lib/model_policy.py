"""Central model policy for DocGen LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.common.model_policy import compact_metadata
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

DocGenModelSlot = Literal["light", "primary", "reason", "image_generation"]


class DocGenModelStep(str, Enum):
    INTENT_CORE = "prepare_global_seed.infer_intent_core"
    FILE_SUMMARY = "prepare_global_seed.summarize_files"
    TITLE_LOCK = "lock_titles_for_chapters.lock_title_for_chapter"
    CHAPTER_EXECUTION_BRIEF = "build_chapter_execution_briefs.build_chapter_execution_brief"
    QUERY_PLANNING = "generate_chapters.query_planning"
    RESEARCH_PURIFY = "generate_chapters.research_purify"
    WRITER = "generate_chapters.writer"
    HEADING_REPAIR = "generate_chapters.heading_repair"
    CHAPTER_REWRITE = "generate_chapters.rewrite"
    MERMAID_PLACEHOLDER = "enhance_chapters.mermaid_placeholder"
    INTERACTIVE_HTML = "enhance_chapters.interactive_html_sidecar"
    CHAPTER_REVIEW = "review_content.review_chapter"
    REPAIR_PATCH = "repair_or_route.surface_section_patch"
    COVER_IMAGE = "cover_sidecar"


@dataclass(frozen=True)
class DocGenModelPolicy:
    step: DocGenModelStep
    call_type: Literal["structured", "text", "image"]
    call_purpose: LLMCallPurpose | None
    model: DocGenModelSlot | None
    max_tokens: int | None = None
    temperature_override: float | None = None
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        """Return kwargs for text/structured completion call sites."""

        kwargs: dict[str, object] = {}
        if self.call_purpose is not None:
            kwargs["call_purpose"] = self.call_purpose
        if self.model is not None and self.model != "image_generation":
            kwargs["model"] = self.model
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.temperature_override is not None:
            kwargs["temperature"] = self.temperature_override
        return kwargs

    def metadata(self) -> dict[str, object]:
        """Return stable observability metadata for one DocGen model call."""

        return {
            "docgen_model_step": self.step.value,
            "docgen_model_slot": self.model or "",
            "docgen_call_type": self.call_type,
        }

    def completion_kwargs_with_metadata(
        self,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(extra_metadata, metadata, self.metadata())
        return kwargs


_POLICIES: dict[DocGenModelStep, DocGenModelPolicy] = {
    DocGenModelStep.INTENT_CORE: DocGenModelPolicy(
        step=DocGenModelStep.INTENT_CORE,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="reason",
        max_tokens=1000,
        note="文档级短意图判断，保留策略推理能力。",
    ),
    DocGenModelStep.FILE_SUMMARY: DocGenModelPolicy(
        step=DocGenModelStep.FILE_SUMMARY,
        call_type="structured",
        call_purpose=LLMCallPurpose.DOCGEN_LIGHT,
        model="light",
        max_tokens=9000,
        note="文件级摘要容易被长 JSON 截断，输入已采样但输出预算仍保持宽松。",
    ),
    DocGenModelStep.TITLE_LOCK: DocGenModelPolicy(
        step=DocGenModelStep.TITLE_LOCK,
        call_type="structured",
        call_purpose=LLMCallPurpose.REASONING,
        model="reason",
        max_tokens=420,
        temperature_override=0.1,
        note="标题输出极短，但要守住 confirmed plan 语义。",
    ),
    DocGenModelStep.CHAPTER_EXECUTION_BRIEF: DocGenModelPolicy(
        step=DocGenModelStep.CHAPTER_EXECUTION_BRIEF,
        call_type="structured",
        call_purpose=LLMCallPurpose.REASONING,
        model="reason",
        max_tokens=900,
        temperature_override=0.1,
        note="章级最小执行 brief，需要稳定抽取教学目标。",
    ),
    DocGenModelStep.QUERY_PLANNING: DocGenModelPolicy(
        step=DocGenModelStep.QUERY_PLANNING,
        call_type="structured",
        call_purpose=LLMCallPurpose.REASONING,
        model="reason",
        max_tokens=1400,
        note="研究查询拆解需要覆盖缺口判断。",
    ),
    DocGenModelStep.RESEARCH_PURIFY: DocGenModelPolicy(
        step=DocGenModelStep.RESEARCH_PURIFY,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN_LIGHT,
        model="light",
        max_tokens=4200,
        note="清洗 dense context，不做重推理。",
    ),
    DocGenModelStep.WRITER: DocGenModelPolicy(
        step=DocGenModelStep.WRITER,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN,
        model="reason",
        max_tokens=9000,
        note="实际 model slot 由 digest mode profile 决定。",
    ),
    DocGenModelStep.HEADING_REPAIR: DocGenModelPolicy(
        step=DocGenModelStep.HEADING_REPAIR,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN_LIGHT,
        model="light",
        max_tokens=7000,
        note="只修结构和标题层级。",
    ),
    DocGenModelStep.CHAPTER_REWRITE: DocGenModelPolicy(
        step=DocGenModelStep.CHAPTER_REWRITE,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN,
        model="primary",
        max_tokens=9000,
        note="章节质量不足时的 bounded rewrite。",
    ),
    DocGenModelStep.MERMAID_PLACEHOLDER: DocGenModelPolicy(
        step=DocGenModelStep.MERMAID_PLACEHOLDER,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN_LIGHT,
        model="light",
        max_tokens=3200,
        note="辅助资产生成，优先低成本。",
    ),
    DocGenModelStep.INTERACTIVE_HTML: DocGenModelPolicy(
        step=DocGenModelStep.INTERACTIVE_HTML,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN,
        model="primary",
        max_tokens=7000,
        temperature_override=0.1,
        note="交互页需要较完整的 HTML 生成能力。",
    ),
    DocGenModelStep.CHAPTER_REVIEW: DocGenModelPolicy(
        step=DocGenModelStep.CHAPTER_REVIEW,
        call_type="structured",
        call_purpose=LLMCallPurpose.DOCGEN_LIGHT,
        model="light",
        max_tokens=3200,
        note="并行结构化审稿，优先速度与成本。",
    ),
    DocGenModelStep.REPAIR_PATCH: DocGenModelPolicy(
        step=DocGenModelStep.REPAIR_PATCH,
        call_type="text",
        call_purpose=LLMCallPurpose.DOCGEN,
        model="primary",
        max_tokens=7000,
        note="直接改正文，需要比 light 更稳。",
    ),
    DocGenModelStep.COVER_IMAGE: DocGenModelPolicy(
        step=DocGenModelStep.COVER_IMAGE,
        call_type="image",
        call_purpose=LLMCallPurpose.IMAGE_GENERATION,
        model="image_generation",
        note="图片模型由 settings.models.image_generation 决定。",
    ),
}


def get_docgen_model_policy(
    step: DocGenModelStep | str,
    *,
    digest_mode: str | None = None,
) -> DocGenModelPolicy:
    resolved_step = step if isinstance(step, DocGenModelStep) else DocGenModelStep(str(step))
    policy = _POLICIES[resolved_step]
    if resolved_step == DocGenModelStep.WRITER:
        mode_profile = get_docgen_mode_profile(digest_mode)
        return replace(policy, model="primary" if mode_profile.is_sprint else "reason")
    return policy


def docgen_completion_kwargs(
    step: DocGenModelStep | str,
    *,
    digest_mode: str | None = None,
) -> dict[str, object]:
    return get_docgen_model_policy(step, digest_mode=digest_mode).completion_kwargs()


def docgen_completion_kwargs_with_metadata(
    step: DocGenModelStep | str,
    *,
    digest_mode: str | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_docgen_model_policy(step, digest_mode=digest_mode).completion_kwargs_with_metadata(
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "DocGenModelPolicy",
    "DocGenModelSlot",
    "DocGenModelStep",
    "docgen_completion_kwargs",
    "docgen_completion_kwargs_with_metadata",
    "get_docgen_model_policy",
]
