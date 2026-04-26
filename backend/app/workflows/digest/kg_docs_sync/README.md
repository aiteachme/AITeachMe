# kg_docs_sync Workflow

Synchronizes KnowledgeUnits, knowledge images, and relations from knowledge markdown.

## Entrypoint
- `run_graph_docs_sync_workflow` in `workflow.py`

## Flow
- Split the published knowledge document by level-1 Markdown headings (`#`) as chapters.
- Extract KnowledgeUnits for chapters in parallel.
- Resolve extracted and structural relations after all chapter extraction results are merged.
