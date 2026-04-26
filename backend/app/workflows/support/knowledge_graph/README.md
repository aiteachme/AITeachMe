# Support Knowledge Graph Module

This support module hosts non-workflow knowledge-graph business services.

## Scope
- Build orchestration services and status updates
- Graph query/use-case services
- Overview aggregation
- Incremental markdown sync helpers
- Release/rollback and migration utilities

## Note
The canonical graph workflow is `workflows/digest/kg_docs_sync`. The old
`workflows/digest/kg_file_ingest` package is legacy/debug-only; only a few
extractor utilities are still reused until they are moved to a neutral package.
