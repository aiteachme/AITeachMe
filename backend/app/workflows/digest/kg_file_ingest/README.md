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
