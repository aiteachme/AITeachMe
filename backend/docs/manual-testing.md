# Manual Testing

## Start service

```bash
uvicorn app.main:app --reload --port 8000
```

## Basic checks

### Health

```bash
curl http://localhost:8000/api/health
```

### Init

```bash
curl -X POST http://localhost:8000/api/v1/system/init ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

## Subject

### Create subject

```bash
curl -X POST http://localhost:8000/api/v1/subjects/add ^
  -H "Content-Type: application/json" ^
  -d "{\"subject\":\"math\",\"name\":\"Mathematics\",\"description\":\"Manual testing subject\"}"
```

### List subjects

```bash
curl -X POST http://localhost:8000/api/v1/subjects/list ^
  -H "Content-Type: application/json" ^
  -d "{\"page\":1,\"size\":20}"
```

## Files module

### Upload files

Upload immediately starts parsing in the background.

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/upload" ^
  -F "files=@C:\path\to\lesson1.pdf" ^
  -F "files=@C:\path\to\lesson2.docx"
```

### Query all files

This is now the single read endpoint for file list, parse status, Markdown preview metadata, and asset URLs.

```bash
curl "http://localhost:8000/api/v1/subjects/math/files"
```

### Read one asset

Use the `asset_base_url` and `assets[].url` returned by the files query response.

```bash
curl "http://localhost:8000/api/v1/subjects/math/files/1/assets/figure-1.png"
```

### Delete one file

```bash
curl -X DELETE "http://localhost:8000/api/v1/subjects/math/files/1"
```

### Delete multiple files

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/delete" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[2,3]}"
```

## Knowledge document

### Build document

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/docgen/build" ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"Focus on final exam review and key formulas.\"}"
```

### Query built document

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/docgen/get" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

## Notes

1. The files module no longer exposes separate parse or retry APIs.
2. Upload is the only write entry for parse start.
3. `GET /files` returns full records, including Markdown content and asset URLs for preview.
4. Frontend previews should always resolve images through the returned asset base URL.
