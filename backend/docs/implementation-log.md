# Implementation Notes

## Current API shape

- Layering follows `api -> services -> repositories -> models`.
- API responses use the shared `ApiResponse` envelope.
- Long-running build flows report `pending`, `processing`, `completed`, or `failed`.
- File upload starts ingest automatically.
- The files module now reads through one query endpoint:
  - `GET /api/v1/subjects/{subject}/files`
- File assets are exposed through runtime static URLs and are not part of the documented files API surface.
- Delete operations remain available for files, knowledge docs, chat history, and exams.

## Files refactor summary

- Removed the separate parse trigger from the public files API.
- Removed the separate retry trigger from the public files API.
- Merged list and detail preview needs into the unified files query response.
- Standardized frontend preview to consume Markdown content and asset URLs from the same payload.
- Reduced delete behavior to one endpoint for both single-file and batch deletion.

## Data model reminders

- `RawFile` is the source object for ingest.
- Markdown and extracted assets are persisted on disk and referenced by the files response.
- Asset preview must always use the returned runtime URL instead of raw filesystem paths.
