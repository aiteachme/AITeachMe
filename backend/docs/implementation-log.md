# Implementation Log

This file records the actual scope of the current backend API rework.

## Completed

- kept `GET /api/health` unchanged
- kept all other business APIs on `POST`
- renamed runtime discovery to `POST /api/v1/system/init`
- kept auth as scaffolding and renamed session lookup to `POST /api/v1/auth/user`
- renamed subject CRUD to `add / list / get / edit / delete`
- replaced old subject-scoped engine routes with product-facing resources:
  - `files/*`
  - `knowledge/*`
  - `chat/*`
  - `exam/*`
  - `profile/*`
- removed unused old route modules:
  - `ingest.py`
  - `digest.py`
  - `interact.py`
  - `examine.py`
- introduced a two-stage content lifecycle:
  - `RawFile` for uploads and parse results
  - `DocSet` for one knowledge build
  - `Document` for digest outputs under a doc set
- added supporting persistence tables:
  - `doc_set`
  - `doc_build_job`
  - `doc_set_source_file`
  - `document`
  - `document_outline_node`
  - `document_chunk`
- changed digest persistence from the old knowledge document model to the new document model
- added `files/get` so parsed markdown preview is separate from file status
- made `knowledge/build` consume multiple parsed files and produce one `docset_id`
- added lightweight startup migration for new `raw_file` columns on older local databases
- updated README and manual local testing docs
- simplified `.gitignore` to ignore the full runtime `data/` tree and manual scratch files

## Important Decisions

- `subject` stays the public top-level workspace term
- external API is resource-first, internal implementation still keeps the five-engine split
- `files` owns upload and parse preview
- `knowledge` owns digest build and its outputs
- `chat`, `exam`, and `profile` remain subject-scoped product capabilities
- old route paths are not kept as runtime aliases
- this round favors manual smoke testing over tracked unit tests

## Current MVP Simplifications

- one selected source file currently becomes one `Document` inside a `DocSet`
- a future round can split one source file into multiple categorized documents without changing the public API
- parsed assets are structurally supported, but current parsers may still produce empty asset lists depending on file type

## Not Done Yet

- real email registration and login
- password hashing
- token or session persistence
- auth-protected multi-user isolation
- richer digest job orchestration beyond the current background task model
- production-grade database migrations for every historical local schema variant
