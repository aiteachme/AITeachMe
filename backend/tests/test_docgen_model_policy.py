from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.workflows.digest.kg_doc_sync.lib.model_policy import (
    KGDocSyncModelStep,
    get_kg_doc_sync_model_policy,
    kg_doc_sync_completion_kwargs,
)
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs,
    get_docgen_model_policy,
)


def test_docgen_model_policy_routes_tiers_and_bounds_noncritical_steps() -> None:
    systematic_writer = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="systematic")
    sprint_writer = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="sprint")
    intent_core = docgen_completion_kwargs(DocGenModelStep.INTENT_CORE)

    assert systematic_writer["model"] == "reason"
    assert sprint_writer["model"] == "primary"
    assert intent_core["overall_timeout_s"] >= intent_core["timeout"]
    assert systematic_writer[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert "task_type" not in systematic_writer

    for step in (DocGenModelStep.RESEARCH_PURIFY, DocGenModelStep.HEADING_REPAIR):
        kwargs = docgen_completion_kwargs(step, digest_mode="sprint")

        assert kwargs["model"] == "light"
        assert kwargs["timeout"] < systematic_writer["timeout"]
        assert kwargs["overall_timeout_s"] < systematic_writer["overall_timeout_s"]
        assert kwargs["max_retries"] < systematic_writer["max_retries"]


def test_docgen_writer_model_slot_still_follows_digest_mode() -> None:
    kwargs = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="sprint")

    assert kwargs["model"] == "primary"
    assert kwargs["timeout"] == 120


def test_docgen_intent_core_uses_extended_overall_timeout() -> None:
    kwargs = docgen_completion_kwargs(DocGenModelStep.INTENT_CORE, digest_mode="systematic")
    metadata = get_docgen_model_policy(DocGenModelStep.INTENT_CORE).metadata()

    assert kwargs["timeout"] == 90
    assert kwargs["overall_timeout_s"] == 180
    assert metadata["docgen_overall_timeout_s"] == 180


def test_docgen_interactive_html_sets_generation_timeouts_without_forcing_api_mode() -> None:
    kwargs = docgen_completion_kwargs(DocGenModelStep.INTERACTIVE_HTML, digest_mode="systematic")
    metadata = get_docgen_model_policy(DocGenModelStep.INTERACTIVE_HTML).metadata()

    assert "api_mode" not in kwargs
    assert kwargs["timeout"] == 210
    assert kwargs["overall_timeout_s"] == 460
    assert metadata["docgen_timeout_s"] == 210
    assert metadata["docgen_overall_timeout_s"] == 460


def test_docgen_model_policy_metadata_includes_timeout() -> None:
    metadata = get_docgen_model_policy(DocGenModelStep.TITLE_LOCK).metadata()

    assert metadata["docgen_model_step"] == "lock_titles_for_chapters.lock_title_for_chapter"
    assert metadata["docgen_timeout_s"] == 60
    assert metadata["docgen_overall_timeout_s"] == 180
    assert metadata["docgen_max_retries"] == 3
    assert metadata["docgen_provider_native_web_search_policy"] == "off"
    assert metadata["docgen_provider_native_file_search_policy"] == "off"


def test_docgen_noncritical_cleanup_steps_fail_fast() -> None:
    for step in (DocGenModelStep.RESEARCH_PURIFY, DocGenModelStep.HEADING_REPAIR):
        kwargs = docgen_completion_kwargs(step, digest_mode="sprint")
        metadata = get_docgen_model_policy(step).metadata()

        assert kwargs["model"] == "light"
        assert kwargs["timeout"] == 30
        assert kwargs["overall_timeout_s"] == 40
        assert kwargs["max_retries"] == 1
        assert metadata["docgen_timeout_s"] == 30
        assert metadata["docgen_overall_timeout_s"] == 40
        assert metadata["docgen_max_retries"] == 1


def test_kg_doc_sync_model_policy_disables_provider_native_tools_by_default() -> None:
    kwargs = kg_doc_sync_completion_kwargs(KGDocSyncModelStep.SECTION_GRAPH)
    metadata = get_kg_doc_sync_model_policy(KGDocSyncModelStep.SECTION_GRAPH).metadata()

    assert kwargs[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert metadata["kg_doc_sync_provider_native_web_search_policy"] == "off"
    assert metadata["kg_doc_sync_provider_native_file_search_policy"] == "off"
