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

## Extraction Boundary

Use `app.workflows.support.knowledge_graph.extraction` as the import surface for
extractor types and functions. The old `digest.kg_file_ingest` workflow has
been removed; docs-sync is the only graph-building digest lane.
