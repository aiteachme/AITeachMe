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
from app.workflows.support.system.settings import build_settings_overview_data


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

    assert entries["models.primary"].editable is False
    assert entries["models.primary"].editable is False
    assert entries["database.url"].editable is False
    assert entries["models.primary"].ui_group
    assert entries["models.primary"].ui_order > 0


def test_settings_model_rejects_removed_low_level_keys() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"ingest": {"parse_concurrency": 99}})

    with pytest.raises(ValidationError):
        Settings.model_validate({"search": {"runtime_cache_ttl_s": 60}})
