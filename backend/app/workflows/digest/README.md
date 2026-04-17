# Digest Module

`digest/` contains workflow lanes only.

## Current Layout

```text
digest/
  __init__.py
  README.md
  planner/
  docgen/
  kg_file_ingest/
  kg_docs_sync/
  common/
  application/
  shared/
  unified/
```

## Notes
- `kg_file_ingest/` and `kg_docs_sync/` are independent workflows and follow the lane skeleton.
- Non-workflow knowledge-graph business services were moved to `workflows/support/knowledge_graph/`.
- Cross-lane shared code stays in `digest/common/`.
