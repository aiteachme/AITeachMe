# kg_docs_sync Workflow

`kg_docs_sync` is the canonical product lane for syncing the latest published
`KnowledgeDoc` Markdown into the knowledge graph. The detailed contract lives in
`FLOW_DESIGN.md`; keep this README intentionally short.

## Entrypoint

- `run_graph_docs_sync_workflow` in `workflow.py`

## Flow

- Load the published knowledge document and DocGen structured context.
- Split Markdown with the same heading rules used by
  `extract_markdown_chapter_chunks`.
- Extract chapter graph candidates in parallel inside the `sync` node.
- Merge LLM candidates, fallback candidates, DocGen backbone items, structural
  edges, and source references.
- Upsert graph entities and mark disappeared sync-managed entities as
  deprecated.

## Tracing

LangGraph nodes carry `node_description` metadata through
`digest.common.node_tracing`. The heavy `sync` node also emits LangSmith
substeps for anchor validation, graph-item extraction, and graph upsert.

## Model Policy

LLM calls used by the docs-sync extractor must take `call_purpose`, model slot,
token limit, and tracing metadata from `lib/model_policy.py`.

## Extraction Boundary

Use `app.workflows.digest.kg_docs_sync.lib.extraction` and
`app.workflows.digest.kg_docs_sync.lib.incremental_sync` for docs-sync
extraction and graph-writing internals. The old `digest.kg_file_ingest`
workflow has been removed; docs-sync is the only graph-building digest lane.
Graph query, overview, and cleanup use-cases also live in `lib/query.py`,
`lib/overview.py`, and `lib/cleanup.py`.
