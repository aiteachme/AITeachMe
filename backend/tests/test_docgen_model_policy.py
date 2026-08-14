from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.workflows.digest.kg_doc_sync.lib.model_policy import (
    KGDocSyncModelStep,
    get_kg_doc_sync_model_policy,
    kg_doc_sync_completion_kwargs,
    kg_doc_sync_course_context_max_chars,
)
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs,
)


def test_docgen_model_policy_routes_tiers_and_bounds_noncritical_steps() -> None:
    systematic_writer = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="systematic")
    sprint_writer = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="sprint")
    intent_core = docgen_completion_kwargs(DocGenModelStep.INTENT_CORE)
    backbone = docgen_completion_kwargs(DocGenModelStep.DOCUMENT_BACKBONE)
    interactive_html = docgen_completion_kwargs(DocGenModelStep.INTERACTIVE_HTML)

    assert systematic_writer["model"] == "reason"
    assert sprint_writer["model"] == "primary"
    assert intent_core["overall_timeout_s"] >= intent_core["timeout"]
    assert backbone["model"] == "reason"
    assert backbone["max_tokens"] == 10000
    assert backbone[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert systematic_writer[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert "task_type" not in systematic_writer
    assert interactive_html["timeout"] == 210
    assert interactive_html["overall_timeout_s"] == 460
    assert "api_mode" not in interactive_html


def test_kg_doc_sync_model_policy_disables_provider_native_tools_by_default() -> None:
    kwargs = kg_doc_sync_completion_kwargs(KGDocSyncModelStep.SECTION_GRAPH)
    metadata = get_kg_doc_sync_model_policy(KGDocSyncModelStep.SECTION_GRAPH).metadata()

    assert kwargs[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert kwargs["timeout"] == 90
    assert kwargs["max_retries"] == 2
    assert kwargs["max_tokens"] == 5000
    assert "overall_timeout_s" not in kwargs
    assert kg_doc_sync_course_context_max_chars() == 1200
    assert metadata["kg_doc_sync_provider_native_web_search_policy"] == "off"
    assert metadata["kg_doc_sync_provider_native_file_search_policy"] == "off"
