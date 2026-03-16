# Manual Testing

This round focuses on direct local smoke testing instead of tracked unit tests.

## 1. Prepare the environment

Install dependencies:

```bash
pip install -e .
```

Create or update `.env`:

```env
LLM_API_KEY=sk-your-api-key-here
APP_MODE=local
AUTH_ENABLED=false
```

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

Open docs:

- `http://localhost:8000/redoc`
- `http://localhost:8000/openapi.json`

## 2. First smoke checks

### Health

```bash
curl http://localhost:8000/api/health
```

### System init

```bash
curl -X POST http://localhost:8000/api/v1/system/init ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v1/system/init" `
  -ContentType "application/json" `
  -Body "{}"
```

## 3. Create a subject

```bash
curl -X POST http://localhost:8000/api/v1/subjects/add ^
  -H "Content-Type: application/json" ^
  -d "{\"subject\":\"math\",\"name\":\"High School Math\",\"description\":\"manual test\"}"
```

List subjects:

```bash
curl -X POST http://localhost:8000/api/v1/subjects/list ^
  -H "Content-Type: application/json" ^
  -d "{\"limit\":20,\"offset\":0}"
```

## 4. Test the files pipeline

Recommended file handling:

- keep sample files outside the repo, or
- place them under `manual-testing/`, which is ignored by git

### Upload multiple files

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/upload" ^
  -F "files=@C:\path\to\lesson1.pdf" ^
  -F "files=@C:\path\to\lesson2.pdf"
```

Expected response:

- `subject`
- `file_ids`
- `filenames`

### List uploaded files

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/list" ^
  -H "Content-Type: application/json" ^
  -d "{\"limit\":20,\"offset\":0}"
```

### Parse selected files

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/parse" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[1,2]}"
```

### Check one file status

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/status" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_id\":1}"
```

### Inspect one parsed result

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/get" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_id\":1}"
```

Acceptance points for the files stage:

1. `files/status` only returns state metadata.
2. `files/get` returns markdown preview separately.
3. You can inspect parse quality before building knowledge.

## 5. Test the knowledge pipeline

### Build one knowledge set from multiple parsed files

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/build" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[1,2],\"title\":\"Probability Review\",\"desc\":\"chapter 1-3 materials\"}"
```

Expected response:

- `docset_id`
- `build_job_id`

### Poll knowledge build status

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/status" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

### List knowledge sets

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/list" ^
  -H "Content-Type: application/json" ^
  -d "{\"limit\":20,\"offset\":0}"
```

### Get one knowledge set and its documents

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/get" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

### Get outline trees

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/tree" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

Acceptance points for the knowledge stage:

1. One build can consume multiple parsed `file_id`s.
2. The backend returns one `docset_id`.
3. `knowledge/get` returns multiple documents under that set.
4. `knowledge/tree` reflects digest output per document.

## 6. Optional downstream checks

### Chat

```bash
curl -N -X POST "http://localhost:8000/api/v1/subjects/math/chat/send" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"Explain conditional probability.\"}"
```

### Exam generation

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/exam/make" ^
  -H "Content-Type: application/json" ^
  -d "{\"num\":5}"
```

### Profile report

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/profile/report" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

## 7. If you only want to test ingest-like behavior

The shortest useful loop is:

1. start backend
2. create one subject
3. upload files
4. parse files
5. call `files/status`
6. call `files/get`

That is enough to verify:

- upload persistence
- parser routing
- markdown generation
- preview separation from status
