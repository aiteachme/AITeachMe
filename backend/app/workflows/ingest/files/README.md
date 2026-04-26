# Ingest Files

`workflows/ingest/files/` is the canonical home for file upload, listing, deletion, and parse-trigger use cases.

## Responsibilities

- Serialize raw file records for API responses.
- Save uploaded files through the configured storage backend.
- Start ingest parse workflows for uploaded files.
- Delete raw files and their associated runtime artifacts.

## Notes

- This module is part of the Ingest engine, but it is not a LangGraph lane.
- Long-running parsing still belongs to `workflows/ingest/fast_parse`; this module coordinates the API-facing file commands.
- Persisted upload artifacts are keyed by stable file uid plus a sanitized filename stem:
  `users/{user}/files/{file_uid}__{safe_stem}/raw.ext`, `markdown.md`, and `assets/`.
  The database keeps the original filename for display; storage keys should not use bare auto-increment ids.
- Subject import/export packages use the same `{file_uid}__{safe_stem}` segment for raw files,
  parsed markdown, and extracted assets inside the archive.
