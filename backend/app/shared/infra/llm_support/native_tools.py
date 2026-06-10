"""Provider-native tool request helpers.

These helpers describe tools owned by the upstream model provider, such as
OpenAI Responses `web_search` and `file_search`. They are intentionally kept
separate from project function tools so business workflows can request native
retrieval without coupling themselves to provider-specific request payloads.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.shared.infra.settings import Settings

PROVIDER_NATIVE_TOOLS_KWARG = "provider_native_tools"
ProviderNativeToolMode = Literal["auto", "force"]
ProviderNativeToolType = Literal["web_search", "file_search"]

_SUPPORTED_TOOL_TYPES = {"web_search", "file_search"}
_WEB_SEARCH_KEYS = {
    "external_web_access",
    "filters",
    "return_token_budget",
    "search_context_size",
    "user_location",
}
_FILE_SEARCH_KEYS = {"vector_store_ids", "max_num_results", "filters"}


def build_provider_native_tools(
    *,
    settings: Settings,
    web_search: bool = False,
    file_search: bool = False,
) -> list[dict[str, Any]]:
    """Build provider-native tool hints from runtime settings and workflow intent."""

    tools: list[dict[str, Any]] = []
    if web_search and settings.llm.native_web_search != "off":
        tools.append({
            "type": "web_search",
            "mode": settings.llm.native_web_search,
            "external_web_access": settings.llm.native_web_search_external_access,
        })

    if file_search and settings.llm.native_file_search != "off":
        vector_store_ids = parse_vector_store_ids(settings.llm.native_file_search_vector_store_ids)
        if vector_store_ids:
            tools.append({
                "type": "file_search",
                "mode": settings.llm.native_file_search,
                "vector_store_ids": vector_store_ids,
                "max_num_results": settings.llm.native_file_search_max_results,
            })
    return tools


def parse_vector_store_ids(raw_value: object) -> list[str]:
    """Parse comma-separated vector store ids from settings or env-shaped values."""

    if isinstance(raw_value, (list, tuple)):
        candidates = raw_value
    else:
        candidates = str(raw_value or "").split(",")
    result: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def has_provider_native_tool_requests(raw_tools: object) -> bool:
    return bool(_normalize_tool_requests(raw_tools))


def provider_native_tool_request_types(raw_tools: object) -> list[str]:
    """Return stable provider-native tool type labels from raw requests."""

    tool_types: list[str] = []
    for request in _normalize_tool_requests(raw_tools):
        tool_type = str(request.get("type") or "").strip()
        if tool_type and tool_type not in tool_types:
            tool_types.append(tool_type)
    return tool_types


def without_provider_native_tools(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Return kwargs safe for call paths that do not use the Responses adapter."""

    clean_kwargs = dict(kwargs)
    clean_kwargs.pop(PROVIDER_NATIVE_TOOLS_KWARG, None)
    return clean_kwargs


def provider_native_tools_for_responses(
    raw_tools: object,
    *,
    allow_auto: bool,
    allow_force: bool,
) -> list[dict[str, Any]]:
    """Return provider-native tools safe to put into a Responses API request."""

    tools: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for request in _normalize_tool_requests(raw_tools):
        mode = _tool_mode(request)
        if mode == "auto" and not allow_auto:
            continue
        if mode == "force" and not allow_force:
            continue

        tool_type = str(request.get("type") or "").strip()
        if tool_type == "web_search":
            tool = _web_search_tool_for_responses(request)
        elif tool_type == "file_search":
            tool = _file_search_tool_for_responses(request)
        else:
            continue
        if not tool:
            continue
        key = (
            tool_type,
            tuple(str(item) for item in tool.get("vector_store_ids", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        tools.append(tool)
    return tools


def _normalize_tool_requests(raw_tools: object) -> list[dict[str, Any]]:
    if raw_tools is None:
        return []
    raw_items = raw_tools if isinstance(raw_tools, list) else [raw_tools]
    requests: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, str):
            tool_type = item.strip()
            request: dict[str, Any] = {"type": tool_type, "mode": "auto"}
        elif isinstance(item, Mapping):
            tool_type = str(item.get("type") or item.get("name") or "").strip()
            request = dict(item)
            request["type"] = tool_type
        else:
            continue
        if request["type"] not in _SUPPORTED_TOOL_TYPES:
            continue
        request["mode"] = _tool_mode(request)
        requests.append(request)
    return requests


def _tool_mode(request: Mapping[str, Any]) -> ProviderNativeToolMode:
    value = str(request.get("mode") or "auto").strip().lower()
    return "force" if value == "force" else "auto"


def _web_search_tool_for_responses(request: Mapping[str, Any]) -> dict[str, Any]:
    tool: dict[str, Any] = {"type": "web_search"}
    for key in _WEB_SEARCH_KEYS:
        if key in request:
            tool[key] = request[key]
    return tool


def _file_search_tool_for_responses(request: Mapping[str, Any]) -> dict[str, Any]:
    vector_store_ids = parse_vector_store_ids(request.get("vector_store_ids"))
    if not vector_store_ids:
        return {}
    tool: dict[str, Any] = {
        "type": "file_search",
        "vector_store_ids": vector_store_ids,
    }
    for key in _FILE_SEARCH_KEYS - {"vector_store_ids"}:
        if key in request and request[key] not in (None, "", [], {}):
            tool[key] = request[key]
    return tool


__all__ = [
    "PROVIDER_NATIVE_TOOLS_KWARG",
    "ProviderNativeToolMode",
    "ProviderNativeToolType",
    "build_provider_native_tools",
    "has_provider_native_tool_requests",
    "parse_vector_store_ids",
    "provider_native_tool_request_types",
    "provider_native_tools_for_responses",
    "without_provider_native_tools",
]
