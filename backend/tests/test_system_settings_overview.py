from __future__ import annotations

from app.workflows.support.system import build_settings_overview_data
from app.shared.infra.config import get_settings


def _entry_map():
    overview = build_settings_overview_data()
    return {
        entry.key: entry
        for section in overview.sections
        for entry in section.entries
    }


def test_settings_overview_redacts_secret_env_values(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example/db")

    entries = _entry_map()

    assert entries["llm.api_key"].secret is True
    assert entries["llm.api_key"].status == "configured"
    assert entries["llm.api_key"].value is None
    assert entries["llm.api_key"].display_value == "已配置"
    assert entries["database.url"].secret is True
    assert entries["database.url"].value is None

    get_settings.cache_clear()


def test_settings_overview_groups_config_and_env(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")

    overview = build_settings_overview_data()
    sections = {section.id: section for section in overview.sections}
    entries = _entry_map()

    assert {"runtime", "models", "ingest", "search", "storage", "observability"}.issubset(sections)
    assert entries["runtime.mode"].source == "runtime"
    assert entries["models.primary"].source == "config"
    assert entries["search.searxng_url"].source == "env"
    assert entries["search.searxng_url"].display_value == "https://search.example.com"
    assert overview.notes

    get_settings.cache_clear()
