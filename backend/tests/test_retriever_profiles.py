from __future__ import annotations

from app.shared.infra.config.settings import Settings


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
