"""Tool facade with metadata filtering and policy-aware execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.shared.infra.tools.api import ensure_project_tool_modules_loaded
from app.shared.infra.tools.registry import get_tool_registry

from .context import InfraContext


@dataclass(frozen=True, slots=True)
class ToolCard:
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    source: str = "python"
    risk_level: str = "low"
    scopes: list[str] = field(default_factory=list)
    requires_subject: bool = False
    requires_approval: bool = False


@dataclass(frozen=True, slots=True)
class ToolRunResult:
    name: str
    result: Any = None
    success: bool = True
    blocked: bool = False
    error: str | None = None


def _matches_filters(definition, *, tags: set[str], scopes: set[str]) -> bool:
    if tags and not tags.intersection(set(definition.tags)):
        return False
    if scopes and not scopes.intersection(set(definition.scopes)):
        return False
    return True


def list_tools(
    ctx: InfraContext,
    *,
    tags: list[str] | None = None,
    scopes: list[str] | None = None,
) -> list[ToolCard]:
    """List registered tools visible to the given infra context."""

    del ctx
    ensure_project_tool_modules_loaded()
    tag_filter = {str(item).strip() for item in tags or [] if str(item).strip()}
    scope_filter = {str(item).strip() for item in scopes or [] if str(item).strip()}
    cards: list[ToolCard] = []
    for definition in get_tool_registry().list_all():
        if not _matches_filters(definition, tags=tag_filter, scopes=scope_filter):
            continue
        cards.append(
            ToolCard(
                name=definition.name,
                description=definition.description,
                tags=list(definition.tags),
                source=definition.source,
                risk_level=definition.risk_level,
                scopes=list(definition.scopes),
                requires_subject=definition.requires_subject,
                requires_approval=definition.requires_approval,
            )
        )
    return cards


async def run_tool(
    ctx: InfraContext,
    name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    approved: bool = False,
) -> ToolRunResult:
    """Run one registered tool through the shared policy gate."""

    ensure_project_tool_modules_loaded()
    definition = get_tool_registry().get(name)
    if definition is None:
        return ToolRunResult(name=name, success=False, error=f"工具 `{name}` 未注册")
    args = dict(arguments or {})
    if definition.requires_subject and "subject" not in args:
        if not ctx.subject:
            return ToolRunResult(
                name=name,
                success=False,
                blocked=True,
                error=f"工具 `{name}` 需要 subject 上下文。",
            )
        args["subject"] = ctx.subject
    try:
        result = await get_tool_registry().execute(name, _approval_granted=approved, **args)
        return ToolRunResult(name=name, result=result)
    except PermissionError as exc:
        return ToolRunResult(name=name, success=False, blocked=True, error=str(exc))
    except Exception as exc:
        return ToolRunResult(name=name, success=False, error=str(exc))


__all__ = ["ToolCard", "ToolRunResult", "list_tools", "run_tool"]
