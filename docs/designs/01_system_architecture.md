# 01. 系统架构

最后更新：2026-04-19

本文只描述当前代码真实架构，不记录历史迁移过程。

## 1. 一句话架构

AITeachMe 当前是一个前后端分离的资料驱动 AI 学习系统：

```text
frontend React
  -> FastAPI api
  -> workflows 业务层
  -> repositories / shared.infra / models / schemas
  -> SQLite/PostgreSQL + local/S3 storage
```

核心业务边界是 `Subject`。上传资料、知识文档、知识图谱、对话、考试、画像都围绕同一个 subject 隔离。

## 2. 主业务链路

```text
Subject
  -> RawFile
  -> Ingest: raw_markdowns + assets
  -> Digest Planner: confirmed_plan
  -> Digest DocGen: knowledge_markdowns + KnowledgeDoc
  -> KG lanes: KnowledgeUnit / KnowledgeEdge
  -> Interact / Examine / Profile 消费知识资产
```

关键原则：

- Ingest 只把资料变成可消费 Markdown 和资产。
- Planner 只决定学习方案，不做 deep research。
- DocGen 消费 confirmed plan，生成知识文档和 manifest。
- Interact / Examine / Profile 复用同一套 subject 知识资产。

## 3. 后端分层

当前唯一推荐依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
shared.infra -> shared.kernel
```

| 层 | 职责 |
| --- | --- |
| `api/` | HTTP 路由、鉴权依赖、请求响应转换、SSE Response 包装 |
| `workflows/` | 唯一业务层，承接五大引擎、support 用例和 LangGraph 编排 |
| `repositories/` | 数据库读写封装 |
| `shared/infra/` | LLM、embedding、search、storage、tools、workflow runtime、observability 等基础设施 |
| `models/` | SQLModel 持久化模型 |
| `schemas/` | API / workflow 边界数据结构 |
| `utils/` | 路径、时间、展示等纯工具 |

已删除并禁止恢复：

- `backend/app/services`
- `backend/app/teaching`
- `backend/app/shared/infra/facade`
- `backend/app/shared/infra/guardrails`

## 4. 五大引擎

### Ingest：透视引擎

入口：

- `api/files.py`
- `workflows/support/files/`
- `workflows/ingest/fast_parse/`

职责：

- 保存上传文件。
- 产出 raw markdown。
- 提取/规范化 assets。
- 后台增强 OCR / PDF 解析质量。

### Digest：织网引擎

入口：

- `api/knowledge_docs.py`
- `workflows/digest/planner/`
- `workflows/digest/docgen/`
- `workflows/digest/kg_file_ingest/`
- `workflows/digest/kg_docs_sync/`

职责：

- Planner 生成 confirmed plan。
- DocGen 生成知识文档。
- KG lanes 维护知识图谱。

### Interact：伴读引擎

入口：

- `api/chats.py`
- `workflows/interact/application/`
- `workflows/interact/chat/`

职责：

- 会话管理。
- SSE 流式对话。
- 基于本地知识与上下文生成教学回答。

### Examine：诊断引擎

入口：

- `api/exams.py`
- `workflows/examine/`

职责：

- 出题。
- 组卷。
- 判卷。
- 写回 profile。

### Profile：显影引擎

入口：

- `api/profile.py`
- `workflows/profile/application/`
- `workflows/profile/pipeline/`

职责：

- 掌握度更新。
- 薄弱点识别。
- 复习任务。
- 学科/用户画像。

## 5. 配置边界

配置分三类：

| 类型 | 保存位置 | 例子 |
| --- | --- | --- |
| 项目默认非敏感 settings | `settings_default.yaml` | 模型名、并发、检索策略 |
| 用户级非敏感 settings 覆盖 | 用户数据库 `user_runtime_settings` | 用户选择的模型名、top_k |
| 环境变量 / 敏感项 | `.env` 或浏览器 localStorage 草稿 | API Key、数据库连接串、SMTP 密码 |

规则：

- 密钥不写入用户 settings 数据库。
- `frontend/src/api/generated/` 由 Orval 生成，不手改。
- 用户 settings 覆盖按当前 schema 投影，旧 key 自动忽略。

## 6. 基础设施边界

`shared.infra` 按能力包直接使用：

| 能力 | 入口 |
| --- | --- |
| LLM | `app.shared.infra.llm_support` |
| Embedding | `app.shared.infra.embedding` |
| Search / Reader / RAG | `app.shared.infra.search` |
| Tools | `app.shared.infra.tools` |
| Storage | `app.shared.infra.storage` |
| Subject vector status | `app.shared.infra.subject` |
| Workflow runtime / progress | `app.shared.infra.workflow` |
| Execution / sandbox / safety checks | `app.shared.infra.execution` |
| Observability | `app.shared.infra.observability` |
| Runtime paths / mode / tasks | `app.shared.infra.runtime` |

## 7. 当前优先演进方向

1. Ingest Phase 2 持久化任务队列。
2. DocGen repair loop 闭环。
3. Search/reader 持久化缓存。
4. Settings 页面继续做常用/高级配置分层。
5. Profile 学习档案继续投影到 Interact 运行时上下文。

## 8. 一句话

当前架构不是全能 Agent，而是：

```text
Subject 边界 + Workflow 业务编排 + Infra 能力接入 + 本地优先存储
```
