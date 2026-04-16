from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine

from app.models.system import SystemSettingsSnapshot
from app.shared.infra.database.core import _upsert_settings_snapshot
from app.shared.infra.settings import Settings, get_settings
from app.shared.infra.settings.support import load_project_settings_values


def _field_tree(model_type: type[BaseModel]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for name, field in model_type.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            tree[name] = _field_tree(annotation)
        else:
            tree[name] = None
    return tree


def _assert_yaml_covers_settings_model(expected: dict[str, Any], actual: dict[str, Any], prefix: str = "") -> None:
    missing = sorted(set(expected) - set(actual))
    assert not missing, f"settings.yaml missing keys under {prefix or '<root>'}: {missing}"

    for key, child in expected.items():
        if child is None:
            continue
        value = actual.get(key)
        assert isinstance(value, dict), f"settings.yaml key {prefix}{key} must be a mapping"
        _assert_yaml_covers_settings_model(child, value, prefix=f"{prefix}{key}.")


def test_settings_yaml_covers_typed_settings_schema() -> None:
    raw = load_project_settings_values()

    Settings.model_validate(raw)
    _assert_yaml_covers_settings_model(_field_tree(Settings), raw)


def test_settings_rejects_legacy_flat_fields() -> None:
    raw = load_project_settings_values()
    raw["llm_model"] = "legacy-model"

    try:
        Settings.model_validate(raw)
    except Exception:
        return

    raise AssertionError("legacy flat settings fields must not be accepted")


def test_settings_snapshot_is_written_to_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[SystemSettingsSnapshot.__table__])

    settings = get_settings()
    _upsert_settings_snapshot(engine, settings)

    with Session(engine) as session:
        snapshot = session.get(SystemSettingsSnapshot, "runtime")

    assert snapshot is not None
    assert snapshot.settings_json["models"]["primary"] == settings.models.primary
    assert snapshot.settings_json["search"]["provider_timeout_s"] == settings.search.provider_timeout_s
    assert snapshot.settings_hash
    assert "LLM_API_KEY" not in str(snapshot.settings_json)
