# Subjects Support

`workflows/support/subjects/` is the canonical home for subject registry use cases.

## Responsibilities

- Create, list, update, and delete subject records.
- Validate subject ownership before API-facing operations.
- Preview and execute subject deletion across related content.

## Files

- `catalog.py` contains subject create/list/detail/update use cases.
- `deletion.py` contains delete preview and delete execution use cases.
- `lib/deletion.py` contains deletion internals and artifact cleanup.
