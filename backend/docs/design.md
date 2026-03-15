# AITeachMe Backend Design

## 1. 文档目标

本文档描述 `backend/app` 当前真实可运行的后端结构、核心数据流和后续演进边界。

这次重构明确采用以下约束：

- 不变更现有路由路径
- 不变更现有 HTTP 方法
- 不变更现有请求/响应 JSON 结构
- 不引入数据库 schema 迁移
- 重点提升代码可读性、模块职责清晰度和 OpenAPI / Redoc 可读性

本文档区分两类内容：

- 当前实现：已经在仓库中落地并与代码保持一致
- 未来演进：作为后续版本的扩展方向，不应被误解为当前结构

## 2. 当前架构总览

### 2.1 技术栈

| 层 | 当前选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI | 提供异步接口、依赖注入和 OpenAPI 文档生成 |
| 数据库 | SQLite + sqlite-vec | 同时承载关系数据和向量检索，降低部署复杂度 |
| ORM / 数据模型 | SQLModel | 用于表模型和数据库访问 |
| LLM 调用 | LiteLLM | 统一对接聊天与 embedding 模型 |
| 结构化输出 | Instructor | 用于大纲提取、试卷生成等结构化 LLM 输出 |
| Agent 编排 | LangGraph | 目前主要用于 Digest 流程编排 |
| 文档解析 | MarkItDown / PyMuPDF4LLM | 将上传文件转为后续处理使用的 Markdown |

### 2.2 运行时分层

```text
app/
├── main.py                 FastAPI 应用工厂、生命周期、路由注册
├── api/                    路由层，保持 thin controller
├── services/               编排层，连接 API、仓储、agents
├── repositories/           数据访问层，负责 SQLModel CRUD 与查询
├── agents/                 业务能力实现层
├── schemas/                API 请求/响应模型
├── core/                   配置、数据库、日志、异常、LLM/embedding 封装
└── utils/                  轻量工具函数
```

### 2.3 当前引用方向

当前代码约束为单向依赖，避免横向耦合：

- `api -> services -> repositories / agents -> core`
- `schemas` 主要被 `api` 和少量 `services` 用于响应模型装配
- `repositories` 不依赖 `api`
- `agents` 不依赖 `api`

这不是严格的 DDD 或六边形架构，但对当前 MVP 规模足够清晰，并保留了后续拆分空间。

## 3. 当前目录说明

### 3.1 app 目录

```text
app/
├── api/
│   ├── health.py           健康检查
│   ├── upload.py           上传、任务状态、文件列表
│   ├── knowledge.py        大纲与文档查询
│   ├── chat.py             流式对话与历史消息
│   ├── exam.py             出题、交卷、考试历史
│   ├── profile.py          画像、报告、错题本
│   ├── deps.py             公共依赖
│   └── docs.py             OpenAPI 公共响应定义
├── services/
│   ├── upload_service.py   上传与解析编排
│   ├── knowledge_service.py
│   ├── chat_service.py
│   ├── exam_service.py
│   ├── profile_service.py
│   ├── presenters.py       ORM/查询结果 -> API DTO 映射
│   └── upload_support.py   上传路径与聚合状态辅助逻辑
├── repositories/
│   ├── models.py           所有 SQLModel 表与枚举
│   ├── ingest_repo.py
│   ├── knowledge_repo.py
│   ├── chat_repo.py
│   ├── exam_repo.py
│   └── profile_repo.py
├── agents/
│   ├── ingest/             文件解析
│   ├── digest/             Markdown 清洗、大纲提取、切块、向量化、工作流
│   ├── interact/           检索、上下文拼装、流式输出
│   ├── examine/            试卷生成与判分
│   └── profile/            掌握度更新与报告生成
├── schemas/                API 请求/响应模型与 API 枚举
├── core/                   settings、db、llm、embedding、logger、exceptions
└── utils/                  subject 校验等轻量工具
```

### 3.2 为什么不是 `models/` 目录

历史设计文档里曾经规划过 `app/models/` 拆分多个表模型文件，但当前仓库实际没有这样做。

当前真实实现是：

- 所有表模型集中在 `app/repositories/models.py`
- 这样做减少了 MVP 阶段的跳转成本
- 代价是单文件偏大，但目前仍在可维护范围内

因此本文档不再将不存在的 `app/models/` 结构描述为现状。

## 4. 核心数据流

### 4.1 Upload / Ingest

1. `POST /api/v1/upload` 接收文件与 `subject`
2. `upload_service.handle_upload()` 完成：
   - 文件大小校验
   - 临时落盘
   - 创建 `RawFile`
   - 移动到正式路径
3. `upload_service.process_and_parse()` 完成：
   - 更新 `parse_status`
   - 调用 ingest parser 转 Markdown
   - 保存 Markdown 文件
   - 创建 `Knowledge`
4. API 层通过 `BackgroundTasks` 触发 Digest 工作流

### 4.2 Digest

Digest 负责把解析后的 Markdown 变成可读、可检索、可导航的数据。

当前阶段顺序：

1. `clean`
2. `outline`
3. `store_knowledge`
4. `chunk`
5. `embed`

状态持久化字段为 `Knowledge.pipeline_stage`，值为：

- `pending`
- `cleaned`
- `outlined`
- `stored`
- `chunked`
- `embedded`
- `failed`

当前实现特点：

- 用 LangGraph 串联步骤
- 每个步骤成功后统一写回阶段
- `failed` 可恢复为从 `clean` 重新开始
- `embedded` 视为已完成，不再重复执行

### 4.3 Interact

对话链路由以下部分组成：

1. `chat_service.chat_stream()`
2. `retriever.retrieve()` 执行向量检索
3. `context_builder.build_system_prompt()` 注入：
   - 检索到的知识块
   - 用户划词上下文
   - 最近对话
   - 薄弱点
   - 近期错题
4. `streamer.stream_chat_response()` 执行流式 LLM 输出并持久化对话

当前对话响应保持为 SSE，不改协议。

### 4.4 Examine

试卷链路：

1. `exam_service.create_exam()`
2. `agents.examine.generator.generate_exam()` 使用结构化输出生成题目
3. 保存 `Exam` 和 `Question`
4. `exam_service.submit_exam()` 触发判分
5. `agents.examine.grader.grade_exam()`：
   - 客观题规则判分
   - 主观题 LLM 判分
   - 错题分析
   - 更新画像

### 4.5 Profile

画像链路：

1. `tracker.update_profiles_from_grading()` 按知识点增量更新掌握度
2. `reporter.generate_report()` 聚合：
   - overall mastery
   - weak points top 5
   - LLM 生成复习建议

## 5. 数据模型

当前所有表位于 `app/repositories/models.py`。

关键表如下：

| 表 | 用途 |
| --- | --- |
| `raw_file` | 上传文件元数据与解析状态 |
| `knowledge` | 解析后的知识文档及 digest 阶段 |
| `chunk` | 面向检索的知识块 |
| `chunk_embeddings` | sqlite-vec 虚表，保存 chunk embedding |
| `knowledge_graph_node` | 文档大纲树节点 |
| `chat_message` | 历史问答记录 |
| `exam` | 考卷主表 |
| `question` | 考卷题目 |
| `exam_submission` | 交卷记录 |
| `answer_record` | 每题作答结果 |
| `mistake` | 错题与错因分析 |
| `user_profile` | 按知识点聚合的掌握度画像 |

说明：

- 本次重构不修改以上表结构
- 本次重构不新增迁移脚本
- 重点优化的是代码组织与文档表达，而非持久化模型

## 6. API 设计约束

### 6.1 兼容性约束

为了保持前端兼容，本次重构明确不做以下改动：

- 不把现有查询型 `POST` 改成 `GET`
- 不重命名现有路径
- 不重命名现有字段
- 不调整 SSE 响应格式

### 6.2 本次增强点

虽然接口契约不变，但 OpenAPI 文档应更清晰：

- 每个 endpoint 增加 summary / description / response_description
- 公共错误响应使用统一模型
- 请求/响应字段增加描述与示例
- 用 API 枚举补足 `parse_status`、`pipeline_stage`、`question_type` 等字段说明

## 7. 当前已知边界

### 7.1 当前结构的优点

- 对小团队和 MVP 开发速度友好
- SQLite + sqlite-vec 部署简单
- `api / services / repositories / agents` 边界对当前规模足够清楚
- 通过 `schemas` 能较好支撑 Redoc/OpenAPI

### 7.2 当前结构的限制

- `repositories/models.py` 仍然偏大
- 部分 service 仍承担了少量 DTO 组装职责
- 单体 SQLite 适合单机场景，不适合高并发横向扩容
- Digest / Examine / Interact 的流程编排深度还不一致

## 8. 未来演进

以下内容属于未来方向，不代表当前实现：

### 8.1 模型拆分

可以在后续版本将 `repositories/models.py` 拆分为：

- `models/content.py`
- `models/chat.py`
- `models/exam.py`
- `models/profile.py`

前提是：

- 不破坏现有导入路径的稳定性，或先完成统一导入层
- 伴随测试完善一起进行

### 8.2 服务拆分

如果业务规模继续增大，可考虑演进为：

- API Gateway
- Content / Knowledge 服务
- Chat 服务
- Exam 服务
- Profile 服务

当前代码中 `services` 与 `agents` 的边界，就是未来服务拆分的最小雏形。

### 8.3 更强的异步执行

当前 upload 后的 digest 由 FastAPI `BackgroundTasks` 驱动，后续可升级为：

- 任务队列
- 可重试 worker
- 独立 pipeline monitor

但这些都不属于这次重构的范围。

## 9. 本次重构结论

这次 `/app` 重构的落点不是“推翻重来”，而是：

- 保留已验证可运行的对外契约
- 让目录职责更一致
- 让工作流实现更可读
- 让 OpenAPI 更适合前端、测试和后续维护
- 让设计文档只描述真实现状和明确标注的未来方向
