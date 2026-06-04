# Manual Testing

## Start service

```bash
uvicorn app.main:app --reload --reload-dir app --port 9020
```

## Basic checks

### Health

```bash
curl http://localhost:9020/api/health
```

### Init

```bash
curl -X POST http://localhost:9020/api/v1/system/init ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

## Course

### Create course draft

```bash
curl -X POST http://localhost:9020/api/v1/courses/draft ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

### List courses

```bash
curl -X POST http://localhost:9020/api/v1/courses/list ^
  -H "Content-Type: application/json" ^
  -d "{\"page\":1,\"size\":20}"
```

## Files module

### Upload files

Upload immediately starts parsing in the background.

```bash
curl -X POST "http://localhost:9020/api/v1/courses/math/files/upload" ^
  -F "files=@C:\path\to\lesson1.pdf" ^
  -F "files=@C:\path\to\lesson2.docx"
```

### Query all files

This is now the single read endpoint for file list, parse status, Markdown preview metadata, and asset URLs.

```bash
curl "http://localhost:9020/api/v1/courses/math/files"
```

### Delete files

Use the same endpoint for single delete and batch delete.

Delete one:

```bash
curl -X POST "http://localhost:9020/api/v1/courses/math/files/delete" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_id\":1}"
```

Delete many:

```bash
curl -X POST "http://localhost:9020/api/v1/courses/math/files/delete" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[2,3]}"
```

## Knowledge document

### Build document

```bash
curl -X POST "http://localhost:9020/api/v1/courses/math/knowledge/docgen/build" ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"Focus on final exam review and key formulas.\"}"
```

### Query built document

```bash
curl -X POST "http://localhost:9020/api/v1/courses/math/knowledge/docgen/get" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

## Notes

1. The files module no longer exposes separate parse or retry APIs.
2. Upload is the only write entry for parse start.
3. `GET /files` returns full records, including Markdown content and asset URLs for preview.
4. Asset URLs are runtime static paths, not extra documented files APIs.
