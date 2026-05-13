# 01. 系统架构

最后更新：2026-05-13

本文只描述当前代码真实架构，不记录历史迁移过程。

## 1. 一句话架构

AITeachMe 当前是一个前后端分离、可本地运行、可云端部署的资料驱动 AI 学习系统：

```text
frontend React
  -> FastAPI api
  -> workflows 业务层
  -> repositories / shared.infra / models / schemas
  -> SQLite/PostgreSQL + local/S3 storage
```

核心业务边界是 `Course`。上传资料、知识文档、知识图谱、对话、考试、画像都围绕同一个 course 隔离。

系统定位不是“单次问答 Agent”，而是围绕课程知识资产运行的学习闭环：

```text
资料 -> 解析 -> 学习方案 -> 知识文档 -> 知识图谱
                      -> 伴读对话 / 诊断练习 / 学习画像
                      -> 反哺下一次学习
```

## 2. 主业务链路

```text
Course
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
- Interact / Examine / Profile 复用同一套 course 知识资产。
- Profile 的 `study_plan` 是 learner-facing 的主动建议链路，不替代 Digest Planner。

## 3. 端到端运行视图

```text
React Web / Desktop
  -> FastAPI api
  -> workflows
     -> ingest/intake + ingest/fast_parse
     -> digest/planner + digest/docgen + digest/kg_doc_sync
     -> interact/chat
     -> examine/question_build + examine/exam_grade
     -> profile/update + profile/snapshot + profile/study_plan
  -> repositories / shared.infra / models / schemas
  -> SQLite or PostgreSQL + ContentStore or S3
```

运行时要点：

- Web 前端和桌面端都走同一套 API 契约。
- Electron/Tauri local 会启动本地后端；云端部署由独立后端服务承接。
- 本地模式默认 SQLite + 本地 ContentStore；云端模式可接 PostgreSQL + pgvector + S3-compatible OSS。
- LangSmith trace、workflow progress events、token/timing summary 用于排查长链路 AI 任务。

## 4. 后端分层

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

- 旧 services 源层
- 旧 teaching 源层
- `backend/app/shared/infra/facade`
- `backend/app/shared/infra/guardrails`

## 5. 五大引擎

### Ingest：透视引擎

入口：

- `api/files.py`
- `workflows/ingest/intake/`
- `workflows/ingest/fast_parse/`

职责：

- 保存上传文件。
- 产出 raw markdown。
- 提取/规范化 assets。
- 后台增强 OCR / PDF 解析质量。
- 当前开放上传类型以 `workflows/ingest/intake/uploads.py` 为准，包含 PDF、DOCX、Markdown、TXT、JPG/PNG/BMP 等。

### Digest：织网引擎

入口：

- `api/knowledge_docs.py`
- `workflows/digest/planner/`
- `workflows/digest/docgen/`
- `workflows/digest/kg_doc_sync/`

职责：

- Planner 生成 confirmed plan。
- DocGen 生成知识文档。
- KG lanes 维护知识图谱；support 模块负责图谱触发、状态和查询。

### Interact：伴读引擎

入口：

- `api/chats.py`
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
- `workflows/profile/update/`
- `workflows/profile/snapshot/`
- `workflows/profile/study_plan/`

职责：

- 掌握度更新。
- 薄弱点识别。
- 复习任务。
- 课程/用户画像。
- 面向学习者生成主动 study plan。

## 6. 使用形态

| 形态 | 入口 | 主要用途 |
| --- | --- | --- |
| 本地开发 | `uvicorn app.main:app` + `npm run dev` 或根目录 `dev.bat` | 调试前后端、workflow、解析器和模型接入 |
| 桌面本地版 | `packaging/release.bat` 生成 Electron local，Tauri local 可选 | 面向个人本机使用，默认保留本地数据目录 |
| 云端部署 | `infra/`、`docs/deployment/*` | 面向团队或内部验证环境，使用云端数据库和对象存储 |
| 课程包交换 | `.atmx` 导入导出 | 课程知识资产迁移、分发和复用 |

## 7. 配置边界

配置分三类：

| 类型 | 保存位置 | 例子 |
| --- | --- | --- |
| 项目默认非敏感 settings | `shared/infra/settings/defaults.py` + 可选 `PROJECT_SETTINGS_PATH` override | 模型名、并发、检索策略 |
| 用户级非敏感 settings 覆盖 | 用户数据库 `user.runtime_settings_json` | 用户选择的模型名、top_k |
| 环境变量 / 敏感项 | `.env` 或浏览器 localStorage 草稿 | API Key、数据库连接串、SMTP 密码 |

规则：

- 密钥不写入用户 settings 数据库。
- `frontend/src/api/generated/` 由 Orval 生成，不手改。
- 用户 settings 覆盖按当前 schema 投影，旧 key 自动忽略。

## 8. 基础设施边界

`shared.infra` 按能力包直接使用：

| 能力 | 入口 |
| --- | --- |
| LLM | `app.shared.infra.llm_support` |
| Embedding | `app.shared.infra.embedding` |
| Search / Reader / RAG | `app.shared.infra.search` |
| Tools | `app.shared.infra.tools` |
| Storage | `app.shared.infra.storage` |
| Course vector status | `app.shared.infra.course` |
| Workflow runtime / progress | `app.shared.infra.workflow` |
| Execution / sandbox / safety checks | `app.shared.infra.execution` |
| Observability | `app.shared.infra.observability` |
| Runtime paths / mode / tasks | `app.shared.infra.runtime` |

## 9. 工程原则

- `Course` 是业务隔离边界。
- `workflows/` 是唯一业务层。
- `shared.infra` 只接通用能力，不反向理解教学语义。
- 长链路 AI 任务必须有状态、进度、trace 和失败摘要。
- 可选外部能力缺失时，优先保证普通本地链路可用。
- 根 README 可以更偏对外介绍；事实源文档必须以当前代码为准。

## 10. 当前优先演进方向

1. Ingest Phase 2 持久化任务队列。
2. DocGen repair loop 闭环。
3. Search/reader 持久化缓存。
4. Settings 页面继续做常用/高级配置分层。
5. Profile 学习档案继续投影到 Interact 运行时上下文。
6. 公开 README 补齐真实截图、演示 GIF 和课程样例。

## 11. 一句话

当前架构不是通用 Agent 平台，而是：

```text
Course 边界 + Workflow 业务编排 + Infra 能力接入 + 本地优先存储
```
