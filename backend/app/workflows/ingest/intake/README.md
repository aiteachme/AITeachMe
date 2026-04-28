# Ingest Intake

`workflows/ingest/intake/` is the canonical home for Phase 0 file intake: upload, library listing, deletion, and parse dispatch.

## Responsibilities

- Serialize raw file records for API responses.
- Save uploaded files through the configured storage backend.
- Start ingest parse workflows for uploaded files.
- Delete raw files and their associated runtime artifacts.

## Notes

- This module is part of the Ingest engine, but it is not a LangGraph lane.
- It is not a generic file service; it owns RawFile intake and hands parsing off to `workflows/ingest/fast_parse`.
- Persisted upload artifacts are keyed by stable file ID plus a sanitized filename stem:
  `users/{user}/files/{file_id}__{safe_stem}/raw.ext`, `markdown.md`, and `assets/`.
  The database keeps the original filename for display; storage keys should not use bare auto-increment ids.
- Subject import/export packages use the same `{file_id}__{safe_stem}` segment for raw files,
  parsed markdown, and extracted assets inside the archive.
