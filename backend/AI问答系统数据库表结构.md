# AI问答系统数据库表结构文档

## 1. 聊天相关表

### 1.1 chat_message (聊天消息表)

存储用户与AI的对话消息记录。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 消息主键ID |
| subject | str | ✓ | 所属学科标识 |
| user_id | str | ✓ | 用户ID，默认"local" |
| session_id | str | ✓ | 会话ID，标识一次完整对话 |
| turn_id | str | ✓ | 对话轮次ID，一问一答为一个turn |
| source | str | ✓ | 消息来源标识（如"doc_selection"、"quick_chat"） |
| anchor_id | str | ✓ | 文档锚点ID，用于定位文档中的特定位置 |
| selected_text | str | - | 用户选中的文本内容 |
| source_chunk_id | int | - | 来源知识块ID |
| role | str | - | 消息角色（user/assistant） |
| content | str | - | 消息内容 |
| contexts | JSON | - | 检索上下文引用列表（包含chunk_id、document_id、title、header_path、score） |
| created_at | datetime | ✓ | 创建时间 |

**业务说明：**
- 每条消息记录一次用户提问或AI回答
- `turn_id` 将一问一答绑定为一个对话轮次
- `contexts` 字段存储AI回答时引用的知识来源，用于溯源和引用展示
- `source` 区分不同场景的对话（文档问答、快速问答等）

### 1.2 chat_session (会话元信息表)

存储聊天会话的元数据。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | str | PK | 会话ID（UUID） |
| subject | str | ✓ | 所属学科标识 |
| user_id | str | ✓ | 用户ID，默认"local" |
| title | str | - | 会话标题，默认"新会话" |
| source | str | ✓ | 会话来源标识 |
| created_at | datetime | ✓ | 创建时间 |
| updated_at | datetime | ✓ | 更新时间 |
| last_message_at | datetime | ✓ | 最后一条消息时间 |

**业务说明：**
- 一个session包含多条message
- `title` 可用于会话列表展示
- `last_message_at` 用于会话排序

## 2. 知识库相关表

### 2.1 subject (学科空间表)

定义学科/知识空间的基本信息。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 学科主键ID |
| slug | str | ✓ UNIQUE | 学科唯一标识符（URL友好） |
| name | str | - | 学科名称 |
| description | str | - | 学科描述 |
| created_at | datetime | - | 创建时间 |
| updated_at | datetime | - | 更新时间 |

**业务说明：**
- 学科是知识组织的顶层单位
- `slug` 用于URL路由和API调用

### 2.2 raw_file (原始文件表)

存储用户上传的原始资料文件。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 文件主键ID |
| subject | str | ✓ | 所属学科标识 |
| filename | str | - | 原始文件名 |
| filetype | str | - | 文件类型（pdf/pptx/docx等） |
| file_path | str | - | 文件存储路径 |
| markdown_path | str | - | 转换后的Markdown文件路径 |
| asset_dir | str | - | 资源文件目录（图片等） |
| status | str | ✓ | 处理状态（pending/processing/completed/failed） |
| error_message | str | - | 错误信息 |
| created_at | datetime | - | 创建时间 |
| updated_at | datetime | - | 更新时间 |
| **Ingest增强字段** | | | |
| content_hash | str | - | 文件SHA-256哈希值 |
| file_size_bytes | int | - | 文件大小（字节） |
| estimated_pages | int | - | 预估页数/幻灯片数 |
| detected_language | str | - | 检测语言（zh/en/mixed） |
| classification_result | str | - | 分类结果JSON |
| quality_score | float | - | 解析质量总分（0-1） |
| parse_metadata | str | - | 解析元数据JSON |
| image_count | int | - | 提取的图片数量 |
| ingest_status | str | - | Ingest流水线状态 |

**业务说明：**
- 原始文件上传后会经过解析、转换、质量评估等流程
- `ingest_status` 跟踪文件处理流水线状态
- `quality_score` 用于评估文件解析质量

### 2.3 document (文档表)

知识集合中的单篇文档（经过处理的知识单元）。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 文档主键ID |
| subject | str | ✓ | 所属学科标识 |
| source_file_id | int | ✓ FK | 来源原始文件ID（关联raw_file.id） |
| title | str | - | 文档标题 |
| markdown_content | str | - | 完整Markdown内容 |
| current_step | str | ✓ | 当前处理步骤 |
| created_at | datetime | - | 创建时间 |
| updated_at | datetime | - | 更新时间 |

**业务说明：**
- 一个raw_file可能生成一个或多个document
- document是知识检索的基本单位

### 2.4 document_chunk (文档切块表)

文档按章节/段落切分的知识块。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 切块主键ID |
| document_id | int | ✓ FK | 所属文档ID（关联document.id） |
| title | str | - | 切块标题 |
| level | int | - | 标题层级（1-6） |
| header_path | str | - | 标题路径（如"第一章 > 1.1节"） |
| chunk_index | int | UNIQUE | 切块序号（与document_id组成唯一约束） |
| content | str | - | 切块内容 |

**业务说明：**
- 文档按标题层级切分为多个chunk
- chunk是向量检索和引用的最小单位
- `header_path` 用于展示知识来源的层级结构

### 2.5 knowledge_doc (知识文档表)

Digest引擎生成的结构化知识文档（章节级）。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 知识文档主键ID |
| subject | str | ✓ | 所属学科标识 |
| chapter_index | int | - | 章节序号，决定排列顺序 |
| title | str | - | 章节标题 |
| summary | str | - | 50字导读摘要 |
| markdown_content | str | - | 完整Markdown内容 |
| markdown_path | str | - | 磁盘.md文件路径 |
| tags | str | - | JSON数组，章节标签 |
| source_file_ids | str | - | JSON数组，来源RawFile ID列表 |
| word_count | int | - | 字数统计 |
| version | int | - | 版本号 |
| status | str | ✓ | 状态（draft/published/archived） |
| created_at | datetime | - | 创建时间 |
| updated_at | datetime | - | 更新时间 |

**业务说明：**
- AI生成的结构化教学文档
- 一个章节对应一条记录
- 支持版本管理和发布状态控制

### 2.6 docgen_job (文档生成任务表)

跟踪知识文档生成工作流的进度。

| 字段名 | 类型 | 索引 | 说明 |
|--------|------|------|------|
| id | int | PK | 任务主键ID |
| subject | str | ✓ | 所属学科标识 |
| status | str | ✓ | 任务状态（pending/processing/completed/failed） |
| progress | int | - | 进度百分比（0-100） |
| current_step | str | - | 当前处理阶段 |
| total_chapters | int | - | 总章节数 |
| completed_chapters | int | - | 已完成章节数 |
| error_message | str | - | 错误信息 |
| input_file_ids_json | str | - | 输入文件ID JSON数组 |
| user_prompt | str | - | 用户提供的文档生成要求 |
| created_at | datetime | - | 创建时间 |
| updated_at | datetime | - | 更新时间 |

**业务说明：**
- 跟踪异步文档生成任务
- 提供进度反馈给前端

## 3. 数据流转关系

```
用户上传文件
    ↓
raw_file (原始文件存储)
    ↓
document (文档解析)
    ↓
document_chunk (切块索引)
    ↓
向量化 & 检索
    ↓
chat_message (问答记录，contexts字段引用chunk)
```

## 4. 核心业务场景

### 4.1 文档问答流程
1. 用户在文档中选中文本，提出问题
2. 系统创建 `chat_message` (role=user)，记录 `selected_text`、`anchor_id`、`source_chunk_id`
3. 检索相关 `document_chunk`
4. AI生成回答，创建 `chat_message` (role=assistant)，`contexts` 字段记录引用的chunk信息
5. 前端展示回答及引用来源

### 4.2 会话管理
- 用户可创建多个 `chat_session`
- 每个session包含多个 `chat_message`
- 通过 `turn_id` 将一问一答组织为对话轮次
- 支持按session查询历史记录

### 4.3 知识构建
1. 上传文件 → `raw_file`
2. 解析转换 → `document`
3. 切块索引 → `document_chunk`
4. AI生成结构化文档 → `knowledge_doc`（可选）

## 5. 索引设计说明

- **高频查询字段**：subject、session_id、turn_id、source、user_id 均建立索引
- **时间字段**：created_at、last_message_at 建立索引，支持时间排序
- **唯一约束**：subject.slug、(document_chunk.document_id, chunk_index)
- **外键关系**：document.source_file_id → raw_file.id、document_chunk.document_id → document.id
