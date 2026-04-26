# Support Knowledge Graph Module

This support module hosts non-workflow knowledge-graph business services.

## Scope
- Build orchestration services and status updates
- Graph query/use-case services
- Overview aggregation
- Incremental markdown sync helpers
- Product-facing graph extraction adapter in `extraction.py`
- Release/rollback and migration utilities

## Note
The canonical graph workflow is `workflows/digest/kg_docs_sync`. The old
`workflows/digest/kg_file_ingest` package has been removed; product graph code
should import extractor contracts from `workflows/support/knowledge_graph/extraction.py`.
