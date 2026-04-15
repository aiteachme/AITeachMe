# Files Support

`workflows/support/files/` is the canonical home for file upload, listing, deletion, and parse-trigger use cases.

## Responsibilities

- Serialize raw file records for API responses.
- Save uploaded files through the configured storage backend.
- Start ingest parse workflows for uploaded files.
- Delete raw files and their associated runtime artifacts.

## Notes

- This module is a support workflow, not a LangGraph engine lane.
- Long-running parsing still belongs to `workflows/ingest`; this module only coordinates the API-facing command.
