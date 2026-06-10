"""Shared helpers for workflow model-policy modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.shared.infra.llm_support.native_tools import parse_vector_store_ids
from app.shared.infra.settings import Settings

ProviderNativeToolSetting = Literal["off", "settings", "auto", "force"]


def compact_metadata(*parts: Mapping[str, object] | None, **metadata: object) -> dict[str, object]:
    """Merge metadata parts and drop empty values before sending them to tracing."""

    compacted: dict[str, object] = {}
    for part in parts:
        if not part:
            continue
        compacted.update(
            {key: value for key, value in part.items() if value not in (None, "", [], {})}
        )
    compacted.update(
        {key: value for key, value in metadata.items() if value not in (None, "", [], {})}
    )
    return compacted


@dataclass(frozen=True)
class ProviderNativeToolPolicy:
    """Workflow-step policy for upstream provider-native tool hints.

    The boolean intent still comes from the workflow call site. This policy only
    decides whether that intent is allowed and which mode/settings override to use.
    """

    web_search: ProviderNativeToolSetting = "settings"
    file_search: ProviderNativeToolSetting = "settings"
    web_search_external_access: bool | None = None
    file_search_vector_store_ids: tuple[str, ...] | None = None
    file_search_max_results: int | None = None

    @classmethod
    def disabled(cls) -> "ProviderNativeToolPolicy":
        return cls(web_search="off", file_search="off")

    def build(
        self,
        *,
        settings: Settings,
        web_search: bool = False,
        file_search: bool = False,
    ) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        web_mode = _resolve_native_tool_mode(self.web_search, settings.llm.native_web_search)
        if web_search and web_mode != "off":
            tools.append({
                "type": "web_search",
                "mode": web_mode,
                "external_web_access": (
                    settings.llm.native_web_search_external_access
                    if self.web_search_external_access is None
                    else self.web_search_external_access
                ),
            })

        file_mode = _resolve_native_tool_mode(self.file_search, settings.llm.native_file_search)
        if file_search and file_mode != "off":
            vector_store_ids = parse_vector_store_ids(
                self.file_search_vector_store_ids
                if self.file_search_vector_store_ids is not None
                else settings.llm.native_file_search_vector_store_ids
            )
            if vector_store_ids:
                tools.append({
                    "type": "file_search",
                    "mode": file_mode,
                    "vector_store_ids": vector_store_ids,
                    "max_num_results": (
                        self.file_search_max_results
                        or settings.llm.native_file_search_max_results
                    ),
                })
        return tools

    def effective_web_search_mode(self, settings: Settings) -> Literal["off", "auto", "force"]:
        return _resolve_native_tool_mode(self.web_search, settings.llm.native_web_search)

    def effective_file_search_mode(self, settings: Settings) -> Literal["off", "auto", "force"]:
        return _resolve_native_tool_mode(self.file_search, settings.llm.native_file_search)

    def metadata(self, *, prefix: str = "provider_native") -> dict[str, object]:
        metadata: dict[str, object] = {
            f"{prefix}_web_search_policy": self.web_search,
            f"{prefix}_file_search_policy": self.file_search,
        }
        if self.web_search_external_access is not None:
            metadata[f"{prefix}_web_search_external_access"] = self.web_search_external_access
        if self.file_search_vector_store_ids is not None:
            metadata[f"{prefix}_file_search_vector_store_count"] = len(self.file_search_vector_store_ids)
        if self.file_search_max_results is not None:
            metadata[f"{prefix}_file_search_max_results"] = self.file_search_max_results
        return metadata


def _resolve_native_tool_mode(
    policy_value: ProviderNativeToolSetting,
    settings_value: object,
) -> Literal["off", "auto", "force"]:
    if policy_value != "settings":
        return policy_value
    value = str(settings_value or "off").strip().lower()
    if value == "force":
        return "force"
    if value == "auto":
        return "auto"
    return "off"


__all__ = [
    "ProviderNativeToolPolicy",
    "ProviderNativeToolSetting",
    "compact_metadata",
]
