"""Central model policy for DocGen LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.shared.infra.settings import get_settings
from app.workflows.common.model_policy import ProviderNativeToolPolicy, compact_metadata
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile

DocGenModelSlot = Literal["light", "primary", "reason", "image_generation"]
_DOCGEN_OVERALL_TIMEOUT_S = 180


class DocGenModelStep(str, Enum):
    INTENT_CORE = "prepare_global_seed.infer_intent_core"
    FILE_SUMMARY = "prepare_global_seed.summarize_files"
    TITLE_LOCK = "lock_titles_for_chapters.lock_title_for_chapter"
    CHAPTER_EXECUTION_BRIEF = "build_chapter_execution_briefs.build_chapter_execution_brief"
    QUERY_PLANNING = "generate_chapters.query_planning"
    RESEARCH_PURIFY = "generate_chapters.research_purify"
    WRITER = "generate_chapters.writer"
    CHAPTER_REWRITE = "generate_chapters.rewrite"
    MERMAID_PLACEHOLDER = "enhance_chapters.mermaid_placeholder"
    STATIC_HTML_FIGURE = "enhance_chapters.static_html_figure"
    INTERACTIVE_HTML = "enhance_chapters.interactive_html_sidecar"
    CHAPTER_REVIEW = "review_content.review_chapter"
    DOCUMENT_REVIEW = "review_content.document_consistency_review"
    REPAIR_PATCH = "repair_or_route.surface_section_patch"
    COVER_IMAGE = "cover_sidecar"


@dataclass(frozen=True)
class DocGenModelPolicy:
    step: DocGenModelStep
    call_type: Literal["structured", "text", "image"]
    model: DocGenModelSlot | None
    max_tokens: int | None = None
    timeout_s: int | None = None
    overall_timeout_s: int = _DOCGEN_OVERALL_TIMEOUT_S
    max_retries: int = 3
    temperature: float | None = None
    provider_native_tools: ProviderNativeToolPolicy = field(default_factory=ProviderNativeToolPolicy.disabled)
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        """Return kwargs for text/structured completion call sites."""

        kwargs: dict[str, object] = {}
        if self.model is not None and self.model != "image_generation":
            kwargs["model"] = self.model
        if self.call_type != "image":
            kwargs[PROVIDER_NATIVE_TOOLS_KWARG] = self.provider_native_tools.build(
                settings=get_settings(),
                web_search=False,
                file_search=False,
            )
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        kwargs["overall_timeout_s"] = self.overall_timeout_s
        kwargs["max_retries"] = self.max_retries
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def metadata(self) -> dict[str, object]:
        """Return stable observability metadata for one DocGen model call."""

        return {
            "docgen_model_step": self.step.value,
            "docgen_model_slot": self.model or "",
            "docgen_call_type": self.call_type,
            "docgen_timeout_s": self.timeout_s or 0,
            "docgen_overall_timeout_s": self.overall_timeout_s,
            "docgen_max_retries": self.max_retries,
            **self.provider_native_tools.metadata(prefix="docgen_provider_native"),
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
        model="reason",
        max_tokens=1400,
        timeout_s=90,
        temperature=0.1,
        note="文档级短意图判断，保留策略推理能力。",
    ),
    DocGenModelStep.FILE_SUMMARY: DocGenModelPolicy(
        step=DocGenModelStep.FILE_SUMMARY,
        call_type="structured",
        model="light",
        max_tokens=12000,
        timeout_s=120,
        temperature=0.1,
        note="文件级摘要容易被长 JSON 截断，输入已采样但输出预算仍保持宽松。",
    ),
    DocGenModelStep.TITLE_LOCK: DocGenModelPolicy(
        step=DocGenModelStep.TITLE_LOCK,
        call_type="structured",
        model="reason",
        max_tokens=700,
        timeout_s=60,
        temperature=0.1,
        note="标题输出极短，但要守住 confirmed plan 语义。",
    ),
    DocGenModelStep.CHAPTER_EXECUTION_BRIEF: DocGenModelPolicy(
        step=DocGenModelStep.CHAPTER_EXECUTION_BRIEF,
        call_type="structured",
        model="reason",
        max_tokens=1400,
        timeout_s=120,
        temperature=0.1,
        note="章级最小执行 brief，需要稳定抽取教学目标。",
    ),
    DocGenModelStep.QUERY_PLANNING: DocGenModelPolicy(
        step=DocGenModelStep.QUERY_PLANNING,
        call_type="structured",
        model="reason",
        max_tokens=2200,
        timeout_s=120,
        temperature=0.2,
        note="研究查询拆解需要覆盖缺口判断。",
    ),
    DocGenModelStep.RESEARCH_PURIFY: DocGenModelPolicy(
        step=DocGenModelStep.RESEARCH_PURIFY,
        call_type="text",
        model="light",
        max_tokens=3000,
        timeout_s=30,
        overall_timeout_s=40,
        max_retries=1,
        temperature=0.1,
        note="清洗 dense context，不做重推理；失败时直接使用原研究材料。",
    ),
    DocGenModelStep.WRITER: DocGenModelPolicy(
        step=DocGenModelStep.WRITER,
        call_type="text",
        model="reason",
        max_tokens=12000,
        timeout_s=120,
        max_retries=5,
        temperature=0.5,
        note="实际 model slot 由 digest mode profile 决定。",
    ),
    DocGenModelStep.CHAPTER_REWRITE: DocGenModelPolicy(
        step=DocGenModelStep.CHAPTER_REWRITE,
        call_type="text",
        model="primary",
        max_tokens=12000,
        timeout_s=120,
        temperature=0.5,
        note="章节质量不足时的 bounded rewrite。",
    ),
    DocGenModelStep.MERMAID_PLACEHOLDER: DocGenModelPolicy(
        step=DocGenModelStep.MERMAID_PLACEHOLDER,
        call_type="text",
        model="light",
        max_tokens=4500,
        timeout_s=120,
        temperature=0.1,
        note="辅助资产生成，优先低成本。",
    ),
    DocGenModelStep.STATIC_HTML_FIGURE: DocGenModelPolicy(
        step=DocGenModelStep.STATIC_HTML_FIGURE,
        call_type="structured",
        model="light",
        max_tokens=2600,
        timeout_s=120,
        temperature=0.1,
        note="结构化规划静态讲义图示，由代码渲染为考试讲义式 HTML/SVG。",
    ),
    DocGenModelStep.INTERACTIVE_HTML: DocGenModelPolicy(
        step=DocGenModelStep.INTERACTIVE_HTML,
        call_type="text",
        model="primary",
        max_tokens=12000,
        timeout_s=120,
        temperature=0.1,
        note="交互页需要较完整的 HTML 生成能力。",
    ),
    DocGenModelStep.CHAPTER_REVIEW: DocGenModelPolicy(
        step=DocGenModelStep.CHAPTER_REVIEW,
        call_type="structured",
        model="light",
        max_tokens=4500,
        timeout_s=120,
        temperature=0.1,
        note="并行结构化审稿，优先速度与成本。",
    ),
    DocGenModelStep.DOCUMENT_REVIEW: DocGenModelPolicy(
        step=DocGenModelStep.DOCUMENT_REVIEW,
        call_type="structured",
        model="reason",
        max_tokens=4200,
        timeout_s=120,
        temperature=0.1,
        note="整本文档一次性跨章一致性复核，只输出问题和可执行回流动作。",
    ),
    DocGenModelStep.REPAIR_PATCH: DocGenModelPolicy(
        step=DocGenModelStep.REPAIR_PATCH,
        call_type="text",
        model="primary",
        max_tokens=1800,
        timeout_s=120,
        temperature=0.5,
        note="只生成局部补丁片段，代码负责插入原章节。",
    ),
    DocGenModelStep.COVER_IMAGE: DocGenModelPolicy(
        step=DocGenModelStep.COVER_IMAGE,
        call_type="image",
        model="image_generation",
        timeout_s=120,
        temperature=0.7,
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
