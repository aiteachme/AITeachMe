# Export Import Support

最后更新：2026-06-15

职责：导出和导入课程级 `.atmx` 包，并支持远程 demo course 列表和导入。

```text
输入: course_id 或 .atmx package
输出: export package / imported course / demo course catalog
```

## 文件

```text
exports.py   # 导出预览、manifest、打包
imports.py   # 导入事务、ID 重映射、失败清理
courses.py   # demo course 目录和远程包下载
limits.py    # 导入导出限制
```

## 1. 导出预览

输入：`course_id`, `user_id`, 导出选项

动作：统计表数量、预计包大小和可导出内容。

输出：导出预览 payload。

## 2. 导出课程包

输入：`course_id`, `user_id`, 导出选项

动作：生成 `.atmx` 归档和 manifest。

输出：

```text
course-name-course-id.atmx
manifest.json
```

默认包含：

```text
course metadata
knowledge_unit
knowledge_edge
published knowledge documents
docgen assets not stored in DB
```

默认不包含：

```text
原始上传二进制文件
vector embeddings
build locks
临时 _build 文件
derived merged_knowledge_base.md
```

## 3. 导入课程包

输入：`.atmx` 文件、当前用户

动作：校验包、重映射 ID、恢复课程、文件元数据、文档和图谱。

输出：新课程 ID 和导入结果。

## 4. Demo Course

输入：远程 demo course 标识

动作：读取公开 catalog，下载 `.atmx`，导入为当前用户课程。

输出：demo course 列表或导入结果。

远程目录：

```text
https://raw.githubusercontent.com/aiteachme/assets/main/demo-courses/
```

## 边界

`export_import` 不重新生成知识文档或图谱；导入后需要的索引/构建任务由对应 workflow 接手。

这是 support 用例，不是 LangGraph lane。
