from __future__ import annotations

from pathlib import Path
import re

import yaml

from app.shared.infra.settings import (
    get_default_settings_values,
    get_project_settings,
    merge_default_settings,
    reset_project_settings_cache,
)
from app.shared.infra.settings.settings import Settings


def test_settings_model_uses_code_defaults_without_project_file(monkeypatch) -> None:
    monkeypatch.delenv("PROJECT_SETTINGS_PATH", raising=False)
    reset_project_settings_cache()

    settings = get_project_settings()
    defaults = get_default_settings_values()

    assert settings.models.primary == defaults["models"]["primary"]
    assert settings.models.embedding == defaults["models"]["embedding"]
    assert settings.ingest.parse_concurrency == defaults["ingest"]["parse_concurrency"]


def test_settings_support_optional_external_override_file(
    monkeypatch, tmp_path: Path
) -> None:
    override_path = tmp_path / "settings.override.yaml"
    override_path.write_text(
        "\n".join(
            [
                "models:",
                "  primary: qwen-flash",
                "  embedding: text-embedding-v4",
                "planner:",
                '  sprint:',
                '    target_length: "3000-10000字"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJECT_SETTINGS_PATH", str(override_path))
    reset_project_settings_cache()

    settings = get_project_settings()

    assert settings.models.primary == "qwen-flash"
    assert settings.models.embedding == "text-embedding-v4"
    assert settings.planner.sprint.target_length == "3000-10000字"


def test_merge_default_settings_recursively_merges_nested_sections() -> None:
    payload = merge_default_settings(
        {"planner": {"sprint": {"target_length": "custom-length"}}}
    )

    assert payload["planner"]["sprint"]["target_length"] == "custom-length"
    assert payload["planner"]["sprint"]["min_chapters"] == 4
    assert payload["planner"]["systematic"]["max_chapters"] == 12


def test_settings_model_validate_accepts_partial_external_override() -> None:
    payload = yaml.safe_load(
        "\n".join(
            [
                "models:",
                "  primary: qwen-flash",
                "planner:",
                '  systematic:',
                '    target_length: "10000-30000字"',
            ]
        )
    ) or {}

    settings = Settings.model_validate(payload)
    defaults = get_default_settings_values()

    assert settings.models.primary == "qwen-flash"
    assert settings.models.embedding == defaults["models"]["embedding"]
    assert settings.planner.systematic.target_length == "10000-30000字"
    assert settings.planner.systematic.min_chapters == defaults["planner"]["systematic"]["min_chapters"]


def test_env_sample_covers_exposed_env_keys() -> None:
    support_settings = Path(__file__).resolve().parents[1].joinpath(
        "app/workflows/support/system/settings.py"
    ).read_text(encoding="utf-8")
    exposed_env_names = set(
        re.findall(r'_env_entry\([^\n]+?"([A-Z0-9_]+)"', support_settings)
    )

    env_sample_text = Path(__file__).resolve().parents[2].joinpath(".env.sample").read_text(
        encoding="utf-8"
    )
    sample_names = set(
        re.findall(r"^(?:#\s*)?([A-Z][A-Z0-9_]+)=", env_sample_text, re.MULTILINE)
    )

    assert sorted(exposed_env_names - sample_names) == []
