# ComputableTextbook P0 Migration Notes

> Scope: naming migration from `KnowledgeNode` to `KnowledgeUnit`.

## Naming Map

| Area | Old name | New name | Compatibility |
| --- | --- | --- | --- |
| Domain entity | `KnowledgeNode` | `KnowledgeUnit` | Python model uses `KnowledgeUnit`; old repository helper wrappers have been removed. |
| DB table | `knowledge_node` | `knowledge_unit` | New model table is `knowledge_unit`; legacy export/import names are still tolerated during the compatibility window. |
| DB foreign keys | `knowledge_node.id` | `knowledge_unit.id` | Existing `*_node_id` column names still reference `knowledge_unit.id` until a later data migration can rename columns safely. |
| API route | `/knowledge/graph/nodes/detail` | `/knowledge/graph/knowledge-units/detail` | Old route has been removed. |
| API request field | `node_id` | `knowledge_unit_id` | `KnowledgeUnitDetailRequest` now requires `knowledge_unit_id`. |
| API response schema | `KnowledgeNode*` | `KnowledgeUnit*` | OpenAPI defaults to `KnowledgeUnit*`; stale generated clients should be regenerated. |
| Repository helpers | `*_node*` | `*_knowledge_unit*` | New code should call `create_knowledge_unit`, `list_knowledge_units_by_subject`, and related helpers. |
| Frontend generated models | `KnowledgeNodeResponse` | `KnowledgeUnitResponse` | Generated client is refreshed from OpenAPI after backend schema export. |

## Operational Notes

- Treat `KnowledgeUnit` as the canonical knowledge entity in new code, UI state, props, and product copy.
- Keep `source_node_id` / `target_node_id` on `KnowledgeEdge` for now because they describe graph endpoints and are part of the existing edge contract, not compatibility aliases.
- Keep profile/exam fields such as `knowledge_node_id` for now because they are persisted column/API contracts outside the P0 repository and graph-detail path; rename them in a dedicated P4/P6 migration.
- Public API docs and generated clients should expose `KnowledgeUnit` only for graph detail.

## Verification Checklist

- Backend OpenAPI exposes `/knowledge/graph/knowledge-units/detail` as the documented detail endpoint.
- Frontend generated code imports `KnowledgeUnitResponse` and calls the `knowledge-units/detail` operation.
- `kg_repo` main workflow call sites use `knowledge_unit` helper names; old `node` helper wrappers are absent.
