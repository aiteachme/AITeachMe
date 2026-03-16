# AiTeachMe Backend

FastAPI backend for subject-scoped AI learning workflows.

## Current API Shape

`GET /api/health` stays unchanged.

All other business APIs use `POST`:

- `POST /api/v1/system/init`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/user`
- `POST /api/v1/subjects/add`
- `POST /api/v1/subjects/list`
- `POST /api/v1/subjects/get`
- `POST /api/v1/subjects/edit`
- `POST /api/v1/subjects/delete`
- `POST /api/v1/subjects/{subject}/files/upload`
- `POST /api/v1/subjects/{subject}/files/parse`
- `POST /api/v1/subjects/{subject}/files/status`
- `POST /api/v1/subjects/{subject}/files/list`
- `POST /api/v1/subjects/{subject}/files/get`
- `POST /api/v1/subjects/{subject}/knowledge/build`
- `POST /api/v1/subjects/{subject}/knowledge/status`
- `POST /api/v1/subjects/{subject}/knowledge/list`
- `POST /api/v1/subjects/{subject}/knowledge/get`
- `POST /api/v1/subjects/{subject}/knowledge/tree`
- `POST /api/v1/subjects/{subject}/chat/send`
- `POST /api/v1/subjects/{subject}/chat/list`
- `POST /api/v1/subjects/{subject}/exam/make`
- `POST /api/v1/subjects/{subject}/exam/submit`
- `POST /api/v1/subjects/{subject}/exam/list`
- `POST /api/v1/subjects/{subject}/profile/list`
- `POST /api/v1/subjects/{subject}/profile/report`
- `POST /api/v1/subjects/{subject}/profile/mistakes`

Resource boundaries:

- `subject` is the top-level workspace term
- `files` owns raw uploads and parse previews
- `knowledge` owns doc-set builds and digest results
- `chat`, `exam`, and `profile` stay product-facing

## Quick Start

### 1. Install dependencies

```bash
pip install -e .
```

### 2. Configure `.env`

Minimum:

```env
LLM_API_KEY=sk-your-api-key-here
APP_MODE=local
AUTH_ENABLED=false
```

### 3. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Open docs

- Health: `http://localhost:8000/api/health`
- OpenAPI: `http://localhost:8000/openapi.json`
- Redoc: `http://localhost:8000/redoc`

## Manual Testing

This round does not add tracked unit tests.

Use:

- [docs/design.md](./docs/design.md)
- [docs/local-dev.md](./docs/local-dev.md)
- [docs/manual-testing.md](./docs/manual-testing.md)
- [docs/implementation-log.md](./docs/implementation-log.md)

## Runtime Notes

- `APP_MODE=local` is the default
- auth endpoints are scaffolding only
- `files/get` is the parse preview endpoint
- `knowledge/build` consumes multiple parsed files and creates one knowledge set
- local runtime data under `data/` and scratch files under `manual-testing/` are ignored by git
- when switching from an older local database, starting from a clean `data/` directory is still the safest option
