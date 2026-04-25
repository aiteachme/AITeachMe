from __future__ import annotations

from app.shared.infra.settings.support import get_retriever_profiles
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search.types import SearchResult
from app.workflows.digest.common.contracts import resolve_digest_retrieval_profile
from app.workflows.digest.docgen.lib.chapter_context import DocGenChapterContextRuntime


def test_docgen_default_profiles_do_not_include_oi_wiki() -> None:
    profiles = get_retriever_profiles()

    for profile_name in (
        "planner_grounding",
        "docgen_balanced",
        "docgen_sprint",
        "docgen_academic",
        "docgen_systematic",
        "docgen_zh_edu",
        "docgen_zh_math",
    ):
        assert "oi_wiki" not in profiles[profile_name]


def test_oi_wiki_is_only_in_explicit_oi_profile() -> None:
    profiles = get_retriever_profiles()

    assert "oi_wiki" in profiles["docgen_oi"]


def test_retrieval_profile_routes_math_without_oi_wiki() -> None:
    assert (
        resolve_digest_retrieval_profile(
            "systematic",
            user_prompt="初中数学",
            subject_name="初中数学体系构建",
        )
        == "docgen_zh_math"
    )


def test_retrieval_profile_only_routes_explicit_oi_topics_to_oi_profile() -> None:
    assert (
        resolve_digest_retrieval_profile("systematic", user_prompt="NOIP 动态规划", subject_name="")
        == "docgen_oi"
    )
    assert (
        resolve_digest_retrieval_profile("systematic", user_prompt="multiple choice practice", subject_name="")
        == "docgen_systematic"
    )


def test_docgen_research_filters_oi_wiki_outside_oi_profile() -> None:
    runtime = DocGenChapterContextRuntime(TracedExecutionContext(subject="math"))
    results = [
        SearchResult(url="https://oi-wiki.org/math/linear-algebra/", title="OI", snippet="", source="duckduckgo"),
        SearchResult(url="https://zh.wikibooks.org/wiki/初中数学", title="数学", snippet="", source="zh_wikibooks"),
    ]

    filtered = runtime._filter_search_results(results, allow_oi_wiki_sources=False)
    assert [item.url for item in filtered] == ["https://zh.wikibooks.org/wiki/初中数学"]

    allowed = runtime._filter_search_results(results, allow_oi_wiki_sources=True)
    assert [item.url for item in allowed] == [item.url for item in results]
