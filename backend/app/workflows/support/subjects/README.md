# Subjects Support

`workflows/support/subjects/` is the canonical home for subject registry use cases.

## Responsibilities

- Create, list, update, and delete subject records.
- Validate subject ownership before API-facing operations.
- Preview and execute subject deletion across related content.

## Files

- `commands.py` contains API-facing subject commands and simple queries.
- `queries.py` re-exports read-oriented helpers for callers that prefer query imports.
- `lib/deletion.py` contains deletion internals and artifact cleanup.
