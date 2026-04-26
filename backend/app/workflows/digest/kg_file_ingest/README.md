# kg_file_ingest Legacy Note

This package is legacy/debug-only. It was originally used to build the graph
directly from parsed Markdown files while DocGen was slow.

The product graph build no longer calls this lane. The canonical knowledge
graph path is now:

```text
docgen publish -> kg_docs_sync -> sync_markdown_knowledge_graph
```

Some low-level extraction utilities under `lib/` are still reused by
`kg_docs_sync`. Do not add new product behavior here; move reusable code to a
neutral docs-sync/common package before deleting the remaining legacy workflow
files.

## Deletion path

`kg_file_ingest` should be removed in small, safe steps:

1. Move `lib/extractor.py` and its tiny dependency surface to a neutral package
   such as `digest/common/kg_extraction` or `workflows/support/knowledge_graph/extraction`.
2. Rename docs-sync tests so they import the neutral extractor package instead
   of `kg_file_ingest`.
3. Delete the old workflow shell: `graph.py`, `workflow.py`, `state.py`,
   `nodes/`, old job lifecycle helpers, and old mutations.
4. Keep `kg_docs_sync` as the only graph-building workflow exposed to product
   code and `langgraph.json`.

Until step 1 is finished, the legacy graph still carries detailed LangSmith
`node_description` metadata so accidental calls are easy to identify and can be
removed from the caller.
