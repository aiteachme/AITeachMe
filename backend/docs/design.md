# API Design

## Summary

The backend now uses a resource-style API externally while keeping the original five-engine architecture internally.

Public resources:

- `subject`
- `files`
- `knowledge`
- `chat`
- `exam`
- `profile`

Internal engines:

- Ingest
- Digest
- Interact
- Examine
- Profile

## Final External API

### System and auth

- `GET /api/health`
- `POST /api/v1/system/init`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/user`

### Subject management

- `POST /api/v1/subjects/add`
- `POST /api/v1/subjects/list`
- `POST /api/v1/subjects/get`
- `POST /api/v1/subjects/edit`
- `POST /api/v1/subjects/delete`

### Files

- `POST /api/v1/subjects/{subject}/files/upload`
- `POST /api/v1/subjects/{subject}/files/parse`
- `POST /api/v1/subjects/{subject}/files/status`
- `POST /api/v1/subjects/{subject}/files/list`
- `POST /api/v1/subjects/{subject}/files/get`

### Knowledge

- `POST /api/v1/subjects/{subject}/knowledge/build`
- `POST /api/v1/subjects/{subject}/knowledge/status`
- `POST /api/v1/subjects/{subject}/knowledge/list`
- `POST /api/v1/subjects/{subject}/knowledge/get`
- `POST /api/v1/subjects/{subject}/knowledge/tree`

### Chat

- `POST /api/v1/subjects/{subject}/chat/send`
- `POST /api/v1/subjects/{subject}/chat/list`

### Exam

- `POST /api/v1/subjects/{subject}/exam/make`
- `POST /api/v1/subjects/{subject}/exam/submit`
- `POST /api/v1/subjects/{subject}/exam/list`

### Profile

- `POST /api/v1/subjects/{subject}/profile/list`
- `POST /api/v1/subjects/{subject}/profile/report`
- `POST /api/v1/subjects/{subject}/profile/mistakes`

## Lifecycle Design

### Files stage

`files` owns raw uploads and parse previews.

Flow:

1. upload files
2. parse selected files
3. inspect `files/status`
4. inspect `files/get`

This keeps parse quality review separate from digest build.

### Knowledge stage

`knowledge` owns digest-oriented builds.

Flow:

1. select multiple parsed files
2. call `knowledge/build`
3. poll `knowledge/status`
4. inspect `knowledge/get`
5. inspect `knowledge/tree`

Current implementation detail:

- one build creates one `DocSet`
- one selected source file becomes one `Document` under that `DocSet`

That is an implementation detail, not a public API limitation.

## Internal Data Model

Main entities:

- `RawFile`
- `DocSet`
- `DocBuildJob`
- `DocSetSourceFile`
- `Document`
- `DocumentOutlineNode`
- `DocumentChunk`

This lets the backend represent:

- multiple parsed source files
- one knowledge build that groups them
- multiple digest documents under one knowledge set

## Engine Mapping

- Ingest Engine
  - `files/upload`
  - `files/parse`
- Digest Engine
  - `knowledge/build`
  - `knowledge/status`
  - `knowledge/list`
  - `knowledge/get`
  - `knowledge/tree`
- Interact Engine
  - `chat/send`
  - `chat/list`
- Examine Engine
  - `exam/make`
  - `exam/submit`
  - `exam/list`
- Profile Engine
  - `profile/list`
  - `profile/report`
  - `profile/mistakes`
