# Export Import Support

`workflows/support/export_import/` is the canonical home for subject-level course package export and import use cases.

## Responsibilities

- Preview subject export size and table counts.
- Export a subject into an `.atmx` package. Download filenames use `subject-name-subject-id.atmx`; the manifest keeps stable ids and extension metadata. Original uploaded files are intentionally not packaged.
- Import an `.atmx` package as a new subject.
- List remote demo-course packages from the configured OSS catalog when `S3_PUBLIC_BASE_URL` is configured.

## Module Split

- `exports.py`: 导出预览、打包、manifest 与导出侧共享规则
- `imports.py`: 导入事务、ID 重映射、文件落盘与失败清理
- `courses.py`: 演示课程目录读取与远程 `.atmx` 下载；未配置 `S3_PUBLIC_BASE_URL` 时不读取 OSS

## Runtime Paths

- 演示课程主源：使用现有 `S3_PUBLIC_BASE_URL` 下固定的 `demo-courses/`
- 默认课程索引：`<S3_PUBLIC_BASE_URL>/demo-courses/catalog/v1/index.json`
- 课程索引由本机私有脚本 `scripts/private/demo_course_package.py` 自动维护；不要手写 OSS 上的 `index.json`
- 后端读取课程索引时会加 no-cache 请求头和一次性 query，降低 CDN 地域节点返回旧 catalog 的概率；删除或重建演示课程后仍建议在 CDN 控制台刷新 `demo-courses/catalog/v1/index.json`
- 未配置 `S3_PUBLIC_BASE_URL`：不请求 OSS，`GET /api/v1/courses` 返回空列表，手动 `.atmx` 上传导入仍可用

## Demo Course Paths

- `GET /api/v1/courses`: 前端展示课程卡片。
- `POST /api/v1/courses/{filename}/import`: 后端从 OSS 拉取 `.atmx` 后导入当前账号；导入成功后出现在左侧学科列表。

## Export Data Boundary

- Always included: subject metadata plus `knowledge_unit` / `knowledge_edge` graph tables.
- Optional: generated knowledge documents, exam history, chat history, learning profile, and parsed source metadata/retrieval cache.
- Not exported: original uploaded binaries (`PDF/DOCX/PPT/...`), duplicated `files/raw_markdowns/*.md`, vector embeddings, build locks, temporary `_build/` files, and derived `merged_knowledge_base.md` files.
- Published knowledge-document markdown is restored from `knowledge_document.markdown_content`; the archive only carries docgen assets that are not in DB, such as the cover image.

This module is a support workflow. It should coordinate repositories, schemas, storage, and models without introducing a parallel engine lane.
