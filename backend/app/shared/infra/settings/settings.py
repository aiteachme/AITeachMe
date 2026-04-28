"""Runtime settings resolved from code defaults and project overrides."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from .defaults import merge_default_settings, merge_settings_values
from .support import (
    DEFAULT_RETRIEVER_FALLBACK,
    DEFAULT_RUNTIME_RETRIEVER_PROFILE,
    get_retriever_profiles,
    load_project_settings_values,
    normalize_openai_compatible_image_model_name,
    normalize_profile_name,
    normalize_retriever_name,
    resolve_runtime_llm_provider,
    resolve_embedding_dimension,
    upgrade_legacy_settings_payload,
)


class _SettingsModel(BaseModel):
    """Base model for settings-shaped runtime sections."""

    model_config = ConfigDict(extra="forbid")


class ModelsSettings(_SettingsModel):
    """Model names shaped like the project settings `models` section."""

    reason: str | None
    primary: str
    light: str | None
    vision: str | None
    embedding: str | None
    embedding_dim: int | None = None
    rerank: str | None
    ocr: str | None
    image_generation: str | None
    speech_to_text: str | None
    text_to_speech: str | None
    video_generation: str | None

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_model_keys(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            upgraded = upgrade_legacy_settings_payload({"models": value})
            return upgraded.get("models", value)
        return value

    @property
    def fast(self) -> str | None:
        """Alias for `light` for call sites that think in speed tiers."""

        return self.light


class LLMSettings(_SettingsModel):
    enforce_request_timeout: bool


class InteractSettings(_SettingsModel):
    history_turns: int


class PlannerModeSettings(_SettingsModel):
    min_chapters: int
    max_chapters: int
    target_length: str


class PlannerSettings(_SettingsModel):
    default_digest_mode: str
    sprint: PlannerModeSettings
    systematic: PlannerModeSettings


class DocgenSettings(_SettingsModel):
    allow_external_search: bool
    generate_cover_image: bool
    generate_interactive_html: bool


class IngestSettings(_SettingsModel):
    max_upload_size_mb: int
    max_files_per_upload: int
    parser_provider: str


class RagSettings(_SettingsModel):
    top_k: int
    similarity_threshold: float
    rerank_top_k: int


class LocalRagSettings(_SettingsModel):
    priority: bool
    min_results: int


class KnowledgeGraphSettings(_SettingsModel):
    sync_after_docgen: bool
    prefetch_during_docgen: bool
    prefetch_concurrency: int
    max_parallel_extractions: int


class ObservabilitySettings(_SettingsModel):
    llm_observability_enabled: bool
    llm_token_summary_enabled: bool
    tracing_enabled: bool


class Settings(_SettingsModel):
    """Project-level runtime settings.

    The public shape mirrors the optional project settings override schema, e.g.
    `settings.models.reason` or one fixed retriever profile resolved in code.

    Code defaults live in `backend/app/shared/infra/settings/defaults.py`.
    `PROJECT_SETTINGS_PATH` may point to an optional external override file.
    """

    models: ModelsSettings
    llm: LLMSettings
    interact: InteractSettings
    planner: PlannerSettings
    docgen: DocgenSettings
    ingest: IngestSettings
    rag: RagSettings
    local_rag: LocalRagSettings
    knowledge_graph: KnowledgeGraphSettings
    observability: ObservabilitySettings

    @model_validator(mode="before")
    @classmethod
    def _merge_code_defaults(cls, value: Any) -> Any:
        if value is None:
            return merge_default_settings()
        if isinstance(value, Mapping):
            return merge_default_settings(upgrade_legacy_settings_payload(value))
        return value

    @property
    def embedding_dim(self) -> int:
        return resolve_embedding_dimension(
            self.normalized_embedding_model,
            configured_dim=self.models.embedding_dim,
        )

    @property
    def normalized_embedding_model(self) -> str | None:
        value = (self.models.embedding or "").strip()
        return value or None

    @property
    def embedding_configured(self) -> bool:
        return self.normalized_embedding_model is not None

    @property
    def embedding_dim_is_explicit(self) -> bool:
        value = self.models.embedding_dim
        return value is not None and int(value) > 0

    @property
    def has_vision_model(self) -> bool:
        return bool((self.models.vision or "").strip())

    @property
    def has_document_ocr_model(self) -> bool:
        return bool((self.models.ocr or "").strip())

    @property
    def has_vision_ocr_model(self) -> bool:
        """Backward-compatible alias for older ingest call sites."""

        return self.has_document_ocr_model

    @property
    def rerank_configured(self) -> bool:
        return bool((self.models.rerank or "").strip())

    @property
    def image_generation_enabled(self) -> bool:
        value = (self.models.image_generation or "").strip()
        return bool(value)

    @property
    def speech_to_text_enabled(self) -> bool:
        return bool((self.models.speech_to_text or "").strip())

    @property
    def text_to_speech_enabled(self) -> bool:
        return bool((self.models.text_to_speech or "").strip())

    @property
    def video_generation_enabled(self) -> bool:
        return bool((self.models.video_generation or "").strip())

    def parse_retrievers(
        self,
        *,
        profile: str | None = None,
        include_local_rag: bool | None = None,
        include_external: bool = True,
        include_fallback: bool = True,
        fallback_retriever: str = DEFAULT_RETRIEVER_FALLBACK,
    ) -> list[str]:
        resolved_profile = normalize_profile_name(profile or DEFAULT_RUNTIME_RETRIEVER_PROFILE)
        profile_names = [
            normalize_retriever_name(item)
            for item in get_retriever_profiles().get(resolved_profile, [])
        ]
        candidate_names = profile_names or [DEFAULT_RETRIEVER_FALLBACK]

        should_include_local_rag = (
            self.local_rag.priority
            if include_local_rag is None
            else include_local_rag
        )
        normalized: list[str] = []
        seen: set[str] = set()

        def _append(name: str) -> None:
            if not name or name in seen:
                return
            seen.add(name)
            normalized.append(name)

        if should_include_local_rag:
            _append("local_rag")
        for item in candidate_names:
            if include_local_rag is False and item in {"local_rag", "rag"}:
                continue
            if not include_external and item not in {"local_rag", "rag"}:
                continue
            _append(item)

        fallback_name = normalize_retriever_name(fallback_retriever)
        if (
            include_fallback
            and include_external
            and fallback_name
            and any(name != "local_rag" for name in normalized)
        ):
            _append(fallback_name)

        return normalized


_SYSTEM_SETTINGS_OVERRIDE: dict[str, Any] = {}
_EFFECTIVE_SETTINGS_CACHE: Settings | None = None


@lru_cache
def get_project_settings() -> Settings:
    return Settings.model_validate(load_project_settings_values())


def get_system_settings_override_payload() -> dict[str, Any]:
    return deepcopy(_SYSTEM_SETTINGS_OVERRIDE)


def set_system_settings_override(payload: Mapping[str, Any] | None) -> Settings:
    global _SYSTEM_SETTINGS_OVERRIDE, _EFFECTIVE_SETTINGS_CACHE

    base_payload = get_project_settings().model_dump(mode="json")
    candidate_override = upgrade_legacy_settings_payload(payload)
    models_payload = candidate_override.get("models")
    if isinstance(models_payload, dict) and "image_generation" in models_payload:
        models_payload["image_generation"] = normalize_openai_compatible_image_model_name(
            models_payload.get("image_generation"),
            runtime_provider=resolve_runtime_llm_provider(),
        )
    candidate_payload = merge_settings_values(base_payload, candidate_override)
    effective = Settings.model_validate(candidate_payload)
    normalized_override = {
        key: value
        for key, value in candidate_override.items()
        if key in base_payload
    }
    _SYSTEM_SETTINGS_OVERRIDE = normalized_override
    _EFFECTIVE_SETTINGS_CACHE = effective
    return effective


def clear_system_settings_override() -> Settings:
    return set_system_settings_override({})


def reset_project_settings_cache() -> None:
    global _EFFECTIVE_SETTINGS_CACHE
    get_project_settings.cache_clear()
    _EFFECTIVE_SETTINGS_CACHE = None


def get_settings() -> Settings:
    global _EFFECTIVE_SETTINGS_CACHE
    if _EFFECTIVE_SETTINGS_CACHE is not None:
        return _EFFECTIVE_SETTINGS_CACHE
    project_settings = get_project_settings()
    if not _SYSTEM_SETTINGS_OVERRIDE:
        _EFFECTIVE_SETTINGS_CACHE = project_settings
        return project_settings
    merged_payload = merge_settings_values(
        project_settings.model_dump(mode="json"),
        _SYSTEM_SETTINGS_OVERRIDE,
    )
    _EFFECTIVE_SETTINGS_CACHE = Settings.model_validate(merged_payload)
    return _EFFECTIVE_SETTINGS_CACHE


__all__ = [
    "DocgenSettings",
    "IngestSettings",
    "InteractSettings",
    "KnowledgeGraphSettings",
    "LocalRagSettings",
    "ModelsSettings",
    "ObservabilitySettings",
    "PlannerModeSettings",
    "PlannerSettings",
    "RagSettings",
    "Settings",
    "clear_system_settings_override",
    "get_settings",
    "get_project_settings",
    "get_system_settings_override_payload",
    "reset_project_settings_cache",
    "set_system_settings_override",
]
