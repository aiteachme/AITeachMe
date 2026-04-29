# Export Import Support

`workflows/support/export_import/` is the canonical home for course-level package export and import use cases.

## Responsibilities

- Preview course export size and table counts.
- Export a course into an `.atmx` package. Download filenames use `course-name-course-id.atmx`; the manifest keeps stable ids and extension metadata. Original uploaded files are intentionally not packaged.
- Import an `.atmx` package as a new course.
- List remote demo-course packages from the configured OSS catalog when `S3_PUBLIC_BASE_URL` is configured.

## Module Split

- `exports.py`: export preview, package building, manifest generation, and shared export rules.
- `imports.py`: import transaction, id remapping, file restore, and failed-import cleanup.
- `courses.py`: demo-course catalog loading and remote `.atmx` download; it does not read OSS when `S3_PUBLIC_BASE_URL` is missing.

## Runtime Paths

- Demo-course root: `<S3_PUBLIC_BASE_URL>/demo-courses/`
- Default catalog index: `<S3_PUBLIC_BASE_URL>/demo-courses/catalog/v1/index.json`
- The catalog index is maintained by `scripts/private/demo_course_package.py`; avoid hand-editing `index.json` on OSS.
- When `S3_PUBLIC_BASE_URL` is not configured, `GET /api/v1/demo-courses` returns an empty list and manual `.atmx` upload import remains available.

## Demo Course Paths

- `GET /api/v1/demo-courses`: list demo-course cards for the frontend.
- `POST /api/v1/demo-courses/{identifier}/import`: download one `.atmx` package from OSS and import it into the current account; after a successful import it appears in the sidebar course list.

## Export Data Boundary

- Always included: course metadata plus `knowledge_unit` / `knowledge_edge` graph tables.
- Optional: generated knowledge documents, exam history, chat history, learning profile, and parsed source metadata/retrieval cache.
- Not exported: original uploaded binaries (`PDF/DOCX/PPT/...`), duplicated `files/raw_markdowns/*.md`, vector embeddings, build locks, temporary `_build/` files, and derived `merged_knowledge_base.md` files.
- Published knowledge-document markdown is restored from `knowledge_document.markdown_content`; the archive only carries docgen assets that are not in DB, such as the cover image.

This module is a support workflow. It should coordinate repositories, schemas, storage, and models without introducing a parallel engine lane.
