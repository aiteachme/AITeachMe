# Local Development

## Environment

Recommended Python version:

- Python 3.10+

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
```

Install the project:

```bash
pip install -e .
```

## Configuration

Create `.env` with at least:

```env
LLM_API_KEY=sk-your-api-key-here
APP_MODE=local
AUTH_ENABLED=false
```

Optional settings:

- `LLM_BASE_URL`
- `LLM_MODEL`
- `EMBEDDING_MODEL`
- `DATA_DIR`
- `MAX_UPLOAD_SIZE_MB`
- `RAG_TOP_K`
- `RAG_SIMILARITY_THRESHOLD`
- `CHAT_HISTORY_TURNS`

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

## Local data

Runtime data is written under `data/` and ignored by git.

Scratch files for manual testing can be stored under `manual-testing/`, which is also ignored.
