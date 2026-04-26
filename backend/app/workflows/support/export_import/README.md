# Export Import Support

`workflows/support/export_import/` is the canonical home for subject-level course package export and import use cases.

## Responsibilities

- Preview subject export size and table counts.
- Export a subject into an `.atmx` package. Download filenames use `subject-name-subject-id.atmx`; the manifest keeps stable ids and extension metadata. Original uploaded files are intentionally not packaged.
- Import an `.atmx` package as a new subject.
- List remote demo-course packages from the configured OSS catalog.

## Module Split

- `exports.py`: 导出预览、打包、manifest 与导出侧共享规则
- `imports.py`: 导入事务、ID 重映射、文件落盘与失败清理
- `courses.py`: 线上演示课程目录读取与远程 `.atmx` 下载

## Runtime Paths

- 演示课程主源：现有 `S3_PUBLIC_BASE_URL` 下固定的 `demo-courses/`
- 默认课程索引：`<S3_PUBLIC_BASE_URL>/demo-courses/catalog/v1/index.json`
- 课程索引由本机私有脚本 `scripts/private/demo_course_package.py` 自动维护；不要手写 OSS 上的 `index.json`

## Demo Course Paths

- `GET /api/v1/courses`: 前端展示课程卡片。
- `POST /api/v1/courses/{filename}/import`: 后端从 OSS 拉取 `.atmx` 后导入当前连接的运行环境；导入成功后出现在左侧学科列表。本地后端就是本机，云端后端就是云端账号。

## Export Data Boundary

- Always included: subject metadata plus `knowledge_unit` / `knowledge_edge` graph tables.
- Optional: generated knowledge documents, exam history, chat history, learning profile, and parsed source markdown cache.
- Not exported: original uploaded binaries (`PDF/DOCX/PPT/...`), vector embeddings, build locks, temporary `_build/` files, and derived `merged_knowledge_base.md` files.
- Published knowledge-document markdown is restored from `knowledge_document.markdown_content`; the archive only carries docgen assets that are not in DB, such as the cover image.

This module is a support workflow. It should coordinate repositories, schemas, storage, and models without introducing a parallel engine lane.
