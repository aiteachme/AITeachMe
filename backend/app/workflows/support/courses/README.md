# Courses Support

`workflows/support/courses/` is the canonical home for course registry use cases.

## Responsibilities

- Create, list, update, and delete course records.
- Validate course ownership before API-facing operations.
- Preview and execute course deletion across related content.

## Files

- `catalog.py` contains course create/list/detail/update use cases.
- `deletion.py` contains delete preview and delete execution use cases.
- `lib/deletion.py` contains deletion internals and artifact cleanup.
