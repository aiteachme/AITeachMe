"""Skill definitions and registration helpers."""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, get_type_hints

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.tracing import langsmith_trace, llm_trace_scope
from app.workflows.common.context import WorkflowContext

logger = structlog.get_logger(__name__)

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass(slots=True)
class SkillContext:
    subject: str
    build_session_id: str = ""
    workflow_context: WorkflowContext | None = None
    planner_session_id: str = ""
    confirmed_plan_id: str = ""
    digest_mode: str = ""
    course_type: str = ""
    retrieval_profile: str = ""
    teaching_action: str = ""
    asset_kind: str = ""
    chapter_index: int | None = None
    llm_caller: Callable[..., Awaitable[Any]] | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def resolve_llm_caller(self) -> Callable[..., Awaitable[Any]]:
        return self.llm_caller or acompletion_with_fallback

    def trace_metadata(self, **extra: Any) -> dict[str, Any]:
        metadata = dict(self.extra_metadata)
        if self.planner_session_id:
            metadata.setdefault("planner_session_id", self.planner_session_id)
        if self.confirmed_plan_id:
            metadata.setdefault("confirmed_plan_id", self.confirmed_plan_id)
        if self.digest_mode:
            metadata.setdefault("digest_mode", self.digest_mode)
        if self.course_type:
            metadata.setdefault("course_type", self.course_type)
        if self.retrieval_profile:
            metadata.setdefault("retrieval_profile", self.retrieval_profile)
        if self.teaching_action:
            metadata.setdefault("teaching_action", self.teaching_action)
        if self.asset_kind:
            metadata.setdefault("asset_kind", self.asset_kind)
        if self.chapter_index is not None:
            metadata.setdefault("chapter_index", self.chapter_index)
        metadata.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
        return metadata


@dataclass(slots=True)
class SkillResult:
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    cost_tokens: int = 0


class BaseSkill(ABC):
    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.logger = structlog.get_logger(__name__).bind(
            skill_name=self.name,
            subject=context.subject,
            build_session_id=context.build_session_id,
        )

    @property
    def name(self) -> str:
        return self.__class__.__name__

    async def run(self, **kwargs: Any) -> SkillResult:
        workflow_context = self.context.workflow_context
        workflow_name = workflow_context.workflow_name if workflow_context is not None else ""
        lane = str(workflow_context.metadata.get("lane", "")) if workflow_context is not None else ""
        node = f"skill.{self.name}"
        extra_tags = [f"skill:{self.name}"]
        if self.context.digest_mode:
            extra_tags.append(f"mode:{self.context.digest_mode}")
        if self.context.course_type:
            extra_tags.append(f"course:{self.context.course_type}")
        if self.context.retrieval_profile:
            extra_tags.append(f"retrieval:{self.context.retrieval_profile}")
        if self.context.teaching_action:
            extra_tags.append(f"teaching:{self.context.teaching_action}")
        if self.context.asset_kind:
            extra_tags.append(f"asset:{self.context.asset_kind}")
        if self.context.chapter_index is not None:
            extra_tags.append(f"chapter:{self.context.chapter_index}")
        with langsmith_trace(
            name=node,
            run_type="chain",
            inputs=kwargs,
            subject=self.context.subject,
            build_session_id=self.context.build_session_id,
            workflow=workflow_name,
            lane=lane,
            node=node,
            extra_metadata=self.context.trace_metadata(skill_name=self.name),
            extra_tags=extra_tags,
        ) as run:
            with llm_trace_scope(
                subject=self.context.subject,
                build_session_id=self.context.build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=node,
            ):
                result = await self.execute(**kwargs)
            if run is not None:
                run.end(outputs=_skill_trace_outputs(result))
            return result

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        raise NotImplementedError


@dataclass
class SkillDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    is_async: bool = False
    tags: list[str] = field(default_factory=list)

    def to_tool_definition(self):
        from app.shared.infra.tools.definition import ToolDefinition

        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            handler=self.handler,
            is_async=self.is_async,
        )


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        self._skills[definition.name] = definition
        logger.info("skill_registered", name=definition.name, tags=definition.tags)
        from app.shared.infra.tools.registry import get_tool_registry

        get_tool_registry().register(definition.to_tool_definition())

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def _build_schema(func: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in {"self", "cls"}:
            continue
        annotation = hints.get(name, str)
        properties[name] = {
            "type": _TYPE_MAP.get(annotation, "string"),
            "description": f"Parameter {name}",
        }
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {"type": "object", "properties": properties, "required": required}


def skill(name: str, description: str, *, tags: list[str] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        definition = SkillDefinition(
            name=name,
            description=description,
            parameters=_build_schema(func),
            handler=func,
            is_async=asyncio.iscoroutinefunction(func),
            tags=tags or [],
        )
        get_skill_registry().register(definition)
        return func

    return decorator


def _skill_trace_outputs(result: SkillResult) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "content_length": len(result.content),
        "source_count": len(result.sources),
        "image_count": len(result.images),
        "metadata_keys": sorted(result.metadata.keys()),
    }
    for field_name in (
        "local_hits",
        "web_hits",
        "query_count",
        "scraped_url_count",
        "document_count",
        "candidate_count",
        "filtered_count",
        "selected_count",
        "curated_source_count",
        "trusted_source_count",
        "local_source_count",
        "web_source_count",
        "unique_domain_count",
    ):
        value = result.metadata.get(field_name)
        if value not in (None, "", [], {}):
            outputs[field_name] = value
    for field_name in ("fallback_used", "purify_used"):
        value = result.metadata.get(field_name)
        if value is not None:
            outputs[field_name] = bool(value)
    compression_mode = str(result.metadata.get("compression_mode") or "").strip()
    if compression_mode:
        outputs["compression_mode"] = compression_mode
    retriever_stats = result.metadata.get("retriever_stats")
    if isinstance(retriever_stats, Mapping) and retriever_stats:
        outputs["retriever_names"] = sorted(str(name) for name in retriever_stats.keys())
        outputs["retriever_call_count"] = sum(
            int((stats or {}).get("query_count", 0) or 0)
            for stats in retriever_stats.values()
            if isinstance(stats, Mapping)
        )
    return outputs


__all__ = [
    "BaseSkill",
    "SkillContext",
    "SkillDefinition",
    "SkillRegistry",
    "SkillResult",
    "get_skill_registry",
    "skill",
]
