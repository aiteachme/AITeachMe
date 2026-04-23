from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.shared.infra.settings import (
    Settings,
    clear_system_settings_override,
    get_project_settings,
    get_settings,
    set_system_settings_override,
)
from app.workflows.support.system.settings import (
    _normalize_user_settings_payload,
    build_settings_overview_data,
)


def test_get_settings_merges_system_runtime_override() -> None:
    clear_system_settings_override()
    project = get_project_settings()
    original = project.models.primary

    overridden = set_system_settings_override({"models": {"primary": "unit-test-model"}})
    try:
        assert overridden.models.primary == "unit-test-model"
        assert get_settings().models.primary == "unit-test-model"
        assert get_project_settings().models.primary == original
    finally:
        clear_system_settings_override()


def test_settings_overview_local_mode_marks_system_override_editable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.workflows.support.system.settings.is_local_mode",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.workflows.support.system.settings.resolve_app_mode",
        lambda: "local",
    )
    monkeypatch.setattr(
        "app.workflows.support.system.settings.get_system_settings_override_payload",
        lambda: {"models": {"primary": "local-override"}},
    )

    overview = build_settings_overview_data(session=None, user_id=None)
    entries = {
        entry.key: entry
        for section in overview.sections
        for entry in section.entries
    }

    primary_entry = entries["models.primary"]
    assert primary_entry.source == "system_settings"
    assert primary_entry.editable is True
    assert primary_entry.value == "local-override"


def test_settings_overview_cloud_mode_is_read_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.workflows.support.system.settings.is_local_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.workflows.support.system.settings.resolve_app_mode",
        lambda: "cloud",
    )
    monkeypatch.setattr(
        "app.workflows.support.system.settings.get_system_settings_override_payload",
        lambda: {"models": {"primary": "cloud-override"}},
    )

    overview = build_settings_overview_data(session=None, user_id=None)
    entries = {
        entry.key: entry
        for section in overview.sections
        for entry in section.entries
    }

    assert "ops" not in {section.id for section in overview.sections}
    assert "runtime.mode" not in entries
    assert "database.url" not in entries
    assert "storage.backend" not in entries
    assert "search.mcp_tool" not in entries
    assert "search.searxng_url" not in entries
    assert "langsmith.endpoint" not in entries
    assert entries["models.primary"].editable is False
    assert entries["models.primary"].ui_group
    assert entries["models.primary"].ui_order > 0
    assert entries["models.vision"].ui_group == "视觉理解"
    assert entries["models.ocr"].ui_group == "文档解析"
    assert entries["models.vision"].ui_order < entries["models.ocr"].ui_order
    assert entries["models.ocr"].ui_order < entries["models.embedding"].ui_order


def test_settings_model_rejects_removed_low_level_keys() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"ingest": {"parse_concurrency": 99}})

    with pytest.raises(ValidationError):
        Settings.model_validate({"search": {"runtime_cache_ttl_s": 60}})

    with pytest.raises(ValidationError):
        Settings.model_validate({"search": {"retriever_profile": "planner_grounding"}})


def test_get_settings_supports_embedding_dim_override() -> None:
    clear_system_settings_override()
    try:
        overridden = set_system_settings_override(
            {"models": {"embedding": "custom-embedding-model", "embedding_dim": 2048}}
        )
        assert overridden.models.embedding == "custom-embedding-model"
        assert overridden.models.embedding_dim == 2048
        assert get_settings().embedding_dim == 2048
    finally:
        clear_system_settings_override()


def test_settings_model_upgrades_legacy_extract_and_rerank_keys() -> None:
    settings = Settings.model_validate(
        {
            "models": {"extract": "legacy-extract-model"},
            "rag": {"rerank_model": "qwen3-reranker-4b"},
        }
    )

    assert settings.models.light == "legacy-extract-model"
    assert settings.models.rerank == "qwen3-reranker-4b"


def test_normalize_user_settings_payload_normalizes_openai_compatible_image_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")

    payload = _normalize_user_settings_payload(
        {"models": {"image_generation": "doubao-seedream-4-0"}}
    )

    assert payload == {
        "models": {"image_generation": "doubao/doubao-seedream-4-0"}
    }


def test_set_system_settings_override_normalizes_openai_compatible_image_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    clear_system_settings_override()
    try:
        overridden = set_system_settings_override(
            {"models": {"image_generation": "doubao-seedream-4-0"}}
        )
        assert overridden.models.image_generation == "doubao/doubao-seedream-4-0"
        assert get_settings().models.image_generation == "doubao/doubao-seedream-4-0"
    finally:
        clear_system_settings_override()
