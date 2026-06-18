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


def test_docgen_model_policy_sets_step_timeouts() -> None:
    kwargs = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="systematic")

    assert kwargs["timeout"] == 120
    assert kwargs["max_tokens"] == 12000
    assert kwargs["model"] == "reason"
    assert kwargs["max_retries"] == 5
    assert kwargs[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert "task_type" not in kwargs


def test_docgen_writer_model_slot_still_follows_digest_mode() -> None:
    kwargs = docgen_completion_kwargs(DocGenModelStep.WRITER, digest_mode="sprint")

    assert kwargs["model"] == "primary"
    assert kwargs["timeout"] == 120


def test_docgen_model_policy_metadata_includes_timeout() -> None:
    metadata = get_docgen_model_policy(DocGenModelStep.TITLE_LOCK).metadata()

    assert metadata["docgen_model_step"] == "lock_titles_for_chapters.lock_title_for_chapter"
    assert metadata["docgen_timeout_s"] == 60
    assert metadata["docgen_max_retries"] == 3
    assert metadata["docgen_provider_native_web_search_policy"] == "off"
    assert metadata["docgen_provider_native_file_search_policy"] == "off"


def test_kg_doc_sync_model_policy_disables_provider_native_tools_by_default() -> None:
    kwargs = kg_doc_sync_completion_kwargs(KGDocSyncModelStep.SECTION_GRAPH)
    metadata = get_kg_doc_sync_model_policy(KGDocSyncModelStep.SECTION_GRAPH).metadata()

    assert kwargs[PROVIDER_NATIVE_TOOLS_KWARG] == []
    assert metadata["kg_doc_sync_provider_native_web_search_policy"] == "off"
    assert metadata["kg_doc_sync_provider_native_file_search_policy"] == "off"
