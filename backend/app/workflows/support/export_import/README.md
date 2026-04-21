# Export Import Support

`workflows/support/export_import/` is the canonical home for subject-level course package export and import use cases.

## Responsibilities

- Preview subject export size and table counts.
- Export a subject into an `.atmx` package.
- Import an `.atmx` package as a new subject.
- List shared course packages.

## Module Split

- `exports.py`: 导出预览、打包、manifest 与导出侧共享规则
- `imports.py`: 导入事务、ID 重映射、文件落盘与失败清理
- `courses.py`: 本地共享课程目录扫描

## Runtime Paths

- 本地共享课程目录：`backend/data/_courses/`
- 云端演示课程建议由后端统一聚合，不让前端直接拼 OSS 路径

This module is a support workflow. It should coordinate repositories, schemas, storage, and models without introducing a parallel engine lane.
