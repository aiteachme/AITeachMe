"""Runtime settings loaded from project `settings_default.yaml`."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .support import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_RETRIEVER_FALLBACK,
    EMBEDDING_DIM_BY_MODEL,
    get_retriever_profiles,
    load_project_settings_values,
    normalize_retriever_name,
    split_csv_names,
)


class _SettingsModel(BaseModel):
    """Base model for settings-shaped runtime sections."""

    model_config = ConfigDict(extra="forbid")


class ModelsSettings(_SettingsModel):
    """Model names exactly shaped like `settings_default.yaml: models`."""

    reason: str | None = None
    primary: str = "qwen-plus"
    light: str | None = None
    extract: str | None = None
    ocr: str | None = None
    embedding: str = "text-embedding-v3"
    image_generation: str | None = None
    mermaid_generation: str | None = None
    overrides: dict[str, str] = Field(default_factory=dict)

    @property
    def fast(self) -> str | None:
        """Alias for `light` for call sites that think in speed tiers."""

        return self.light


class FilesSettings(_SettingsModel):
    max_upload_size_mb: int = 50


class ChatSettings(_SettingsModel):
    history_turns: int = 10


class PlannerModeSettings(_SettingsModel):
    min_chapters: int
    max_chapters: int
    target_length: str


class PlannerSettings(_SettingsModel):
    default_digest_mode: str = "sprint"
    default_tone: str = "encouraging"
    allow_external_search: bool = True
    grounding_timeout_s: float = 10.0
    sketch_timeout_s: float = 30.0
    intent_timeout_s: float = 20.0
    compose_timeout_s: float = 45.0
    sprint: PlannerModeSettings = Field(
        default_factory=lambda: PlannerModeSettings(
            min_chapters=3,
            max_chapters=6,
            target_length="3000-5000字",
        )
    )
    systematic: PlannerModeSettings = Field(
        default_factory=lambda: PlannerModeSettings(
            min_chapters=5,
            max_chapters=12,
            target_length="10000-15000字",
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _merge_partial_mode_settings(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)

        def merge_mode(key: str, defaults: dict[str, Any]) -> None:
            existing = data.get(key)
            if isinstance(existing, Mapping):
                data[key] = {**defaults, **dict(existing)}

        merge_mode(
            "sprint",
            {
                "min_chapters": 3,
                "max_chapters": 6,
                "target_length": "3000-5000字",
            },
        )
        merge_mode(
            "systematic",
            {
                "min_chapters": 5,
                "max_chapters": 12,
                "target_length": "10000-15000字",
            },
        )
        return data


class DocgenSettings(_SettingsModel):
    max_parallel_chapters: int = 20
    io_parallelism: int = 20
    max_research_queries: int = 3
    retrieval_timeout_s: float = 18.0
    read_timeout_s: float = 12.0


class IngestSettings(_SettingsModel):
    parse_concurrency: int = 5
    parser_timeout_s: int = 90


class RagSettings(_SettingsModel):
    top_k: int = 5
    similarity_threshold: float = 0.3
    rerank_model: str | None = None
    rerank_top_k: int = 3


class SearchSettings(_SettingsModel):
    max_results_per_query: int = 5
    scrape_timeout_s: int = 20
    provider_timeout_s: float = 6.0
    total_timeout_s: float = 12.0
    read_timeout_s: float = 10.0
    parallel_retrievers: bool = True
    max_parallel_retrievers: int = 4
    fusion_k: int = 60
    runtime_cache_enabled: bool = True
    runtime_cache_ttl_s: int = 900
    runtime_cache_max_entries: int = 256
    searxng_base_url: str = ""
    retriever_profiles: dict[str, list[str] | str] = Field(default_factory=dict)


class WebSearchSettings(_SettingsModel):
    retriever: str = "duckduckgo"
    retrievers: str = ""
    retriever_profile: str = ""
    retriever_profiles: dict[str, list[str] | str] = Field(default_factory=dict)


class LocalRagSettings(_SettingsModel):
    priority: bool = True
    min_results: int = 2


class RuntimeSettings(_SettingsModel):
    llm_concurrency_limit: int = 20
    default_token_budget: int = 4000


class EmbeddingSettings(_SettingsModel):
    batch_size: int = 10
    batch_delay_s: float = 0.1


class DigestSettings(_SettingsModel):
    timing_top_k: int = 5
    token_summary_enabled: bool = True
    chapter_priors_timeout_ms: int = 0


class KnowledgeGraphSettings(_SettingsModel):
    extract_max_parallelism: int = 20


class ObservabilitySettings(_SettingsModel):
    llm_observability_enabled: bool = True
    tracing_enabled: bool = True
    langsmith_max_text_chars: int = 2000
    llm_observability_max_records: int = 5000


class SafetySettings(_SettingsModel):
    guardrails_enabled: bool = True


class CacheSettings(_SettingsModel):
    enabled: bool = False
    ttl_s: int = 3600
    max_entries: int = 1000


class GenerationSettings(_SettingsModel):
    enable_image_generation: bool = False
    enable_mermaid_generation: bool = True


class Settings(_SettingsModel):
    """Project-level runtime settings.

    The public shape mirrors repo-root `settings_default.yaml`, e.g.
    `settings.models.reason` or `settings.search.provider_timeout_s`.

    The settings object intentionally does not mirror legacy flat names; call
    sites should use the same nested paths as `settings_default.yaml`.
    """

    models: ModelsSettings = Field(default_factory=ModelsSettings)
    files: FilesSettings = Field(default_factory=FilesSettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    planner: PlannerSettings = Field(default_factory=PlannerSettings)
    docgen: DocgenSettings = Field(default_factory=DocgenSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    rag: RagSettings = Field(default_factory=RagSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    web_search: WebSearchSettings = Field(default_factory=WebSearchSettings)
    local_rag: LocalRagSettings = Field(default_factory=LocalRagSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    digest: DigestSettings = Field(default_factory=DigestSettings)
    knowledge_graph: KnowledgeGraphSettings = Field(default_factory=KnowledgeGraphSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)

    @property
    def embedding_dim(self) -> int:
        if not self.normalized_embedding_model:
            return 0
        return EMBEDDING_DIM_BY_MODEL.get(
            self.normalized_embedding_model,
            DEFAULT_EMBEDDING_DIM,
        )

    @property
    def normalized_embedding_model(self) -> str | None:
        value = (self.models.embedding or "").strip()
        return value or None

    @property
    def embedding_configured(self) -> bool:
        return self.normalized_embedding_model is not None

    @property
    def has_vision_ocr_model(self) -> bool:
        return bool((self.models.ocr or "").strip())

    @property
    def image_generation_enabled(self) -> bool:
        return bool((self.models.image_generation or "").strip()) or self.generation.enable_image_generation

    @property
    def mermaid_generation_enabled(self) -> bool:
        return bool((self.models.mermaid_generation or "").strip()) or self.generation.enable_mermaid_generation

    def parse_retrievers(
        self,
        *,
        profile: str | None = None,
        include_local_rag: bool | None = None,
        include_fallback: bool = True,
        fallback_retriever: str = DEFAULT_RETRIEVER_FALLBACK,
    ) -> list[str]:
        explicit_names = [
            normalize_retriever_name(item)
            for item in split_csv_names(self.web_search.retrievers)
        ]
        resolved_profile = normalize_retriever_name(
            profile or self.web_search.retriever_profile
        )
        profile_names = [
            normalize_retriever_name(item)
            for item in get_retriever_profiles().get(resolved_profile, [])
        ]
        legacy_names = [
            normalize_retriever_name(item)
            for item in split_csv_names(self.web_search.retriever)
        ]

        if explicit_names:
            candidate_names = explicit_names
        elif profile_names:
            candidate_names = profile_names
        elif legacy_names:
            candidate_names = legacy_names
        else:
            candidate_names = [DEFAULT_RETRIEVER_FALLBACK]

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
            _append(item)

        fallback_name = normalize_retriever_name(fallback_retriever)
        if include_fallback and fallback_name and any(name != "local_rag" for name in normalized):
            _append(fallback_name)

        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate(load_project_settings_values())


__all__ = [
    "CacheSettings",
    "ChatSettings",
    "DigestSettings",
    "DocgenSettings",
    "EmbeddingSettings",
    "FilesSettings",
    "GenerationSettings",
    "IngestSettings",
    "KnowledgeGraphSettings",
    "LocalRagSettings",
    "ModelsSettings",
    "ObservabilitySettings",
    "PlannerModeSettings",
    "PlannerSettings",
    "RagSettings",
    "RuntimeSettings",
    "SafetySettings",
    "SearchSettings",
    "Settings",
    "WebSearchSettings",
    "get_settings",
]
