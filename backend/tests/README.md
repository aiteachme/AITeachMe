# Backend Test Suite

These tests should protect product behavior, not only exercise lines of code.

## Quality Bar

- Prefer the public repository, workflow, or API boundary that owns the behavior.
- Add an API/integration test when routing, dependency injection, headers, cookies, or response shape are part of the contract.
- Use fakes only for slow or external dependencies such as LLM calls, network probes, and object storage.
- Assert both the changed target and the data that must remain untouched.
- For cache tests, assert the first call, cached call, and expiry path.
- For concurrency tests, use explicit events or barriers instead of timing-only sleeps.
- Avoid tests whose only assertion is that code ran without raising.

## Coverage Map

- `test_file_upload_dedup.py`, `test_raw_file_membership.py`: upload identity, course membership, and retry safety.
- `test_api_integration.py`: thin HTTP/API coverage for response shape, dependency overrides, and cache-related headers.
- `test_chats_repo.py`, `test_home_intake_flow.py`: chat persistence, user isolation, and client action turns.
- `test_demo_course_catalog_cache.py`: remote catalog fetch/probe caching and unavailable package handling.
- `test_background_task_registry.py`, `test_llm_concurrency_settings.py`: process-wide concurrency limits and cancellation behavior.
- `test_docgen_*`, `test_digest_material_parallelization.py`, `test_markdown_rendering_normalization.py`: planner/docgen workflow contracts and rendering quality.
- `test_kg_doc_sync_extraction_planning.py`, `test_knowledge_graph_ontology.py`: knowledge graph extraction boundaries and ontology compatibility.
- `test_local_rag.py`, `test_interact_retrieval.py`: local retrieval, vector fallback, and weak-hit merge ordering.

## Coverage Audit

Use coverage as a gap-finding tool before turning it into a global gate:

```powershell
python -m uv run --extra dev --with coverage coverage run --source=app -m pytest
python -m uv run --extra dev --with coverage coverage report --skip-covered
```

Prefer raising coverage first on touched, high-risk paths instead of forcing a low-signal global threshold.
