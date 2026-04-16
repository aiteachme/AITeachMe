from __future__ import annotations

from app.shared.infra.config import support
from app.shared.infra.config.settings import Settings
from app.shared.infra.search.factory import get_available_retriever_names, get_configured_retriever_names


def test_default_retriever_profiles_do_not_include_wikipedia() -> None:
    settings = Settings()

    assert settings.parse_retrievers(profile="planner_grounding") == [
        "local_rag",
        "searxng",
        "bocha",
        "duckduckgo",
    ]
    assert settings.parse_retrievers(profile="docgen_systematic") == [
        "local_rag",
        "searxng",
        "tavily",
        "arxiv",
        "semantic_scholar",
        "duckduckgo",
    ]


def test_available_retrievers_filter_out_unconfigured_providers(monkeypatch) -> None:
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BING_API_KEY", raising=False)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    names = get_available_retriever_names(
        [
            "local_rag",
            "searxng",
            "tavily",
            "bocha",
            "bing",
            "exa",
            "brave",
            "duckduckgo",
            "arxiv",
        ]
    )

    assert names == ["local_rag", "duckduckgo", "arxiv"]


def test_factory_configured_retrievers_skip_unavailable_providers(monkeypatch) -> None:
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)

    names = get_configured_retriever_names(
        profile="docgen_systematic",
        include_local_rag=True,
        include_fallback=True,
    )

    assert names == ["local_rag", "arxiv", "semantic_scholar", "duckduckgo"]


def test_settings_parse_retrievers_keeps_declared_profile_order(monkeypatch) -> None:
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)

    settings = Settings()

    assert settings.parse_retrievers(profile="planner_grounding") == [
        "local_rag",
        "searxng",
        "bocha",
        "duckduckgo",
    ]


def test_retriever_profiles_can_be_overridden_from_project_config(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "web_search:",
                "  retriever_profiles:",
                "    planner_grounding: [local_rag, duckduckgo, exa]",
                "search:",
                "  retriever_profiles:",
                "    docgen_systematic: [local_rag, tavily, exa, duckduckgo]",
            ]
        ),
        encoding="utf-8",
    )

    support.get_retriever_profiles.cache_clear()

    try:
        profiles = support.get_retriever_profiles(config_path)
        assert profiles["planner_grounding"] == ["local_rag", "duckduckgo", "exa"]
        assert profiles["docgen_systematic"] == ["local_rag", "tavily", "exa", "duckduckgo"]
    finally:
        support.get_retriever_profiles.cache_clear()
