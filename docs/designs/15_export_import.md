# 15. 学科项目导入与导出

**状态**: 已实现（后端，ContentStore 统一）  
**最后更新**: 2026-04-04

---

## 1. 文档目标

本文档定义 AITeachMe 的**学科级项目导入与导出**功能：

- 将一个 Subject 下的**全部已生成产物**打包成单个可分发文件
- 接收方导入后，**无需重新运行 ingest / digest**，即可直接进入交互、测验、浏览知识文档与图谱
- 同时覆盖**本地部署**和**未来中心化部署**两种场景

---

## 2. 核心场景

| 场景 | 描述 |
| --- | --- |
| **教师分享** | 老师完成一门课程的全部知识构建后，导出分享给学生，学生导入后直接学习 |
| **设备迁移** | 用户在 A 电脑构建完成，导出后到 B 电脑导入继续学习 |
| **备份恢复** | 用户导出当前学科的完整快照，随时可以恢复 |
| **社区分享** | 未来可在社区平台上传/下载预构建学科包，用户即开即用 |
| **云端↔本地** | 在本地构建完成后导出，导入到云端实例；或反之 |

---

## 3. 导出文件格式

### 3.1 格式选型：`.atmx` (AITeachMe eXchange)

采用 **ZIP 压缩包**作为底层格式，自定义扩展名为 `.atmx`。

选型理由：

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| **ZIP** (`.atmx`) | 成熟生态、支持流式、内部可分文件夹、Python 原生 `zipfile` | 不支持增量更新 | ✅ **推荐** |
| SQLite dump | 方便恢复 | 无法包含文件资产、跨 DB 不兼容 | ❌ |
| JSON 包 | 可读 | 大文件性能差、二进制需 Base64 | ❌ |
| tar.gz | 通用 | 不支持随机访问、Windows 原生弱 | ❌ |

### 3.2 `.atmx` 内部结构

```text
subject_export.atmx (ZIP)
├── manifest.json              # 元信息清单
├── db/                        # 结构化数据（JSON 格式，每表一个文件）
│   ├── subject.json
│   ├── raw_file.json
│   ├── retrieval_chunk.json
│   ├── knowledge_document.json
│   ├── knowledge_node.json
│   ├── knowledge_edge.json
│   ├── teaching_unit.json
│   ├── taxonomy_anchor.json
│   ├── curriculum.json
│   ├── theme_tree_node.json
│   ├── unit_dependency.json
│   ├── question_template.json
│   ├── exam_paper.json
│   ├── exam_paper_item.json
│   ├── user_knowledge_state.json
│   ├── chat_session.json
│   └── chat_message.json
├── files/                     # 原始上传文件与解析产物
│   ├── raw_files/
│   ├── raw_markdowns/
│   └── assets/
│       └── <file_id>/
├── knowledge/                 # 知识文档产物
│   ├── chapter_*.md
│   ├── merged_knowledge_base.md
│   └── manifest.json
└── exam/                      # 考试导出产物（如有）
```

### 3.3 `manifest.json` 结构

```json
{
  "format_version": "1.0",
  "app_version": "0.1.0",
  "exported_at": "2026-04-03T00:00:00Z",
  "exporter": "AITeachMe",
  "subject": {
    "slug": "gaodeng-shuxue",
    "name": "高等数学",
    "description": "..."
  },
  "stats": {
    "raw_file_count": 3,
    "knowledge_document_count": 8,
    "knowledge_node_count": 45,
    "knowledge_edge_count": 62,
    "teaching_unit_count": 12,
    "question_template_count": 50,
    "exam_paper_count": 3,
    "chat_session_count": 5,
    "total_file_size_bytes": 15234567
  },
  "options": {
    "include_raw_files": true,
    "include_chat_history": true,
    "include_exam_history": true,
    "include_profile": true
  }
}
```

---

## 4. 数据范围

### 4.1 必须导出的数据（核心产物）

| 层级 | 数据 | 来源 |
| --- | --- | --- |
| 学科元数据 | `subject` | DB |
| 原始文件元数据 | `raw_file` | DB |
| 原始文件二进制 | `raw_files/*` | 文件系统 |
| 解析后 Markdown | `raw_markdowns/*` | 文件系统 |
| 文件资产 | `assets/<file_id>/*` | 文件系统 |
| 检索切块 | `retrieval_chunk` | DB |
| 知识文档 | `knowledge_document` + `knowledge_markdowns/*` | DB + 文件系统 |
| 知识图谱 | `knowledge_node` + `knowledge_edge` | DB |
| 教学单元 | `teaching_unit` | DB |
| 分类锚点 | `taxonomy_anchor` | DB |
| 课程结构 | `curriculum` + `theme_tree_node` + `unit_dependency` | DB |

### 4.2 可选导出的数据

| 数据 | 选项字段 | 默认 | 说明 |
| --- | --- | --- | --- |
| 原始文件二进制 | `include_raw_files` | ✅ | PDF/DOCX 等原始上传文件，关闭后可大幅减小体积 |
| 解析后 Markdown | `include_raw_markdowns` | ✅ | ingest 产出的原始 Markdown |
| 知识文档 | `include_knowledge_docs` | ✅ | digest 构建后的 chapter_*.md 等 |
| 聊天记录 | `include_chat_history` | ✅ | `chat_session` + `chat_message` |
| 题库与考试记录 | `include_exam_history` | ✅ | `question_template` + `exam_paper` + `exam_paper_item` |
| 学习画像 | `include_profile` | ✅ | `user_knowledge_state` |

**常见用法**：

- **教师分发预构建课程包**：关闭 `include_raw_files`、`include_chat_history`、`include_profile`，只保留知识文档和图谱
- **设备迁移/完整备份**：全部打开（默认）
- **只分享构建结果**：关闭 `include_raw_files` + `include_raw_markdowns`

### 4.3 不导出的数据

| 数据 | 原因 |
| --- | --- |
| `chunk_embeddings` | 向量依赖 embedding 模型版本，导入后重建 |
| `user` 表 | 用户身份绑定导入端 |
| `build_status.json` / `.build.lock` | 运行时状态 |
| `_build/` / `temp/` / `debug/` | 中间产物与临时文件 |

---

## 5. 导出流程

### 5.1 API

```text
POST /api/v1/subjects/{subject}/export/preview   — 导出预览（内容摘要）
POST /api/v1/subjects/{subject}/export            — 下载导出包
```

导出请求体：

```json
{
  "include_raw_files": true,
  "include_raw_markdowns": true,
  "include_knowledge_docs": true,
  "include_chat_history": true,
  "include_exam_history": true,
  "include_profile": true
}
```

导出响应：`StreamingResponse` (`application/octet-stream`)

### 5.2 实现流程

1. 校验 subject 存在且无正在进行的构建任务
2. 读取全部 DB 数据，按表序列化为 JSON
3. 通过 ContentStore 统一读取文件产物（local/cloud 透明）
4. 按 options 选择性打包文件
5. 生成 `manifest.json`
6. 打包为 ZIP 流式返回

### 5.3 JSON 序列化格式

每表一个 JSON 文件，记录数组格式：

```json
{
  "table": "knowledge_node",
  "count": 45,
  "records": [{ "id": 1, "subject": "...", "..." : "..." }]
}
```

路径字段在导出时统一转换为相对 `storage_key` 形式，不含绝对路径。

---

## 6. 导入流程

### 6.1 API

```text
POST /api/v1/subjects/import   — 上传并导入 .atmx 文件
```

请求：`multipart/form-data`

可选参数：

```json
{
  "new_subject_name": "高等数学（导入）",
  "overwrite_existing": false
}
```

### 6.2 实现流程

1. 解压 ZIP 到临时目录
2. 读取 `manifest.json` 并校验 `format_version` 兼容性
3. 检查 subject slug 冲突，必要时生成新 slug
4. **按依赖顺序**导入 DB 数据，维护 `old_id → new_id` 映射表：
   ```text
   subject → raw_file → retrieval_chunk
           → knowledge_document → knowledge_node → knowledge_edge
           → teaching_unit → taxonomy_anchor
           → curriculum → theme_tree_node → unit_dependency
           → question_template → exam_paper → exam_paper_item
           → user_knowledge_state
           → chat_session → chat_message
   ```
5. 通过 ContentStore 将文件写入目标 subject（local/cloud 透明）
6. 根据新 ID 和新 subject slug 更新路径字段（使用 ContentStore key 方法）
7. 后台触发 embedding 重建
8. 返回导入结果

### 6.3 关键实现要点

- **ID 重映射**: 导出保留原始 ID，导入时整体重映射。所有外键字段同步更新。
- **路径重建**: 使用 `ContentStore.raw_markdown_key()` 等方法根据新 subject slug 和新 file id 重建路径。
- **事务安全**: DB 导入在一个事务中完成，失败则整体回滚。文件通过 ContentStore 写入。
- **Embedding 重建**: 导入完成后，后台对 `retrieval_chunk` 重建向量索引。
- **冲突处理**: slug 冲突时自动追加后缀（如 `slug-imported-1`）。
- **user_id 映射**: 所有 `user_id` 字段映射为导入端当前用户。

---

## 7. 与中心化部署的兼容

`.atmx` 格式天然跨部署：

- 内部使用 JSON + 相对 `storage_key`，不含绝对路径或 SQLite dump
- 本地 SQLite ↔ 云端 PostgreSQL 双向互通
- **文件打包与解包统一通过 ContentStore** — 同一套代码同时支持本地和云端
- 导入时路径重建使用 `ContentStore.raw_markdown_key()` / `ContentStore.knowledge_doc_key()` 等方法
- 无需根据部署模式切换不同的打包/解包实现

---

## 8. 后端文件清单

| 类型 | 文件 | 职责 |
| --- | --- | --- |
| **[NEW]** | `app/schemas/export_import.py` | API 请求/响应 Schema（仅 API 面） |
| **[NEW]** | `app/services/export_import_service.py` | 核心业务逻辑 + manifest 内部模型 + TABLE_REGISTRY |
| **[NEW]** | `app/api/export_import.py` | API 路由（导出预览 / 导出下载 / 导入上传） |
| **[MODIFY]** | `app/main.py` | 注册新 router |

文件放置遵循现有分层规范：

- `schemas/` 仅放 API 契约模型
- `.atmx` 内部格式模型（`_ExportManifest` 等）以私有类形式放在 service 内部，不外溢到 API 面
- `TABLE_REGISTRY` 是导入导出的唯一配置源；新增/修改表时只需更新注册表

### 8.1 TABLE_REGISTRY 设计

`TABLE_REGISTRY` 是一个 `_TableSpec` 列表，按依赖顺序声明全部 17 张业务表的导出导入规则：

- `name` / `model`：表名与 SQLModel 类
- `subject_field`：如何按 subject 过滤
- `fk_remap`：外键重映射规则 `{字段名: 引用的表名}`
- `optional_group`：可选导出分组

当数据库字段变更时：

- **新增/删除字段**：`model_dump()` / `model_validate()` 自动适配，无需改注册表
- **新增外键**：在注册表对应条目的 `fk_remap` 中加一行
- **新增表**：在注册表中追加一条 `_TableSpec`

---

## 9. 前端入口（待定）

- **导出**: 学科卡片上增加"导出"操作入口
- **导入**: 学科列表顶部增加"导入学科"按钮，支持选择 `.atmx` 文件

前端 API 调用通过 orval 重新生成，不手动编写。

---

## 10. 一句话结论

导入导出的核心目标是"让已构建完成的学科可以打包 → 分发 → 即开即用"。  
格式选择 ZIP-based `.atmx`，内部用 JSON 序列化 DB 数据 + 文件系统产物；  
导入时 ID 重映射 + 路径重建 + 后台 embedding 重建；  
天然兼容本地与云端两套部署。
