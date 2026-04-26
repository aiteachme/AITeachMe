# 设置与配置归属

本文档定义 AITeachMe 当前设置系统的真相边界：哪些配置属于部署输入，哪些属于项目级运行设置，哪些只是模块内部代码常量。

## 1. 当前统一口径

配置分成三层：

1. `env`：部署级、基础设施连接、本地首次启动默认值
2. `code defaults`：代码里的项目默认行为
3. `system_runtime_settings`：数据库中的本地设置页覆盖

另外存在一个**可选**来源：

- `PROJECT_SETTINGS_PATH` 指向的外部项目 settings override 文件

它不是 repo 必备文件，只有显式配置时才参与 merge。

## 2. 各层职责

### 2.1 env

负责：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `DATABASE_URL`
- `AUTH_*`
- `LANGSMITH_*`
- `S3_*`
- `APP_MODE`
- 各搜索 provider 的 API key / endpoint
- `MINERU_API_TOKEN`

在云端部署里，这些属于部署输入；在本地模式里，`.env` 只作为首次启动或数据库未覆盖某个 key 时的默认来源。用户在设置页保存后的值不再写回 `.env`，而是保存到 `system_runtime_settings` 的运行时 env 覆盖层。

### 2.2 code defaults

负责系统能跑起来的项目级默认行为，例如：

- 模型路由默认值
- 上传限制
- planner / docgen 的教学策略默认值
- rag / local_rag 默认值
- `search.retriever_profile`
- `knowledge_graph.sync_after_docgen`
- 观测开关默认值

当前代码默认值集中放在：

- `backend/app/shared/infra/settings/defaults.py`

这也是现在唯一的项目级默认值真源。

### 2.3 system_runtime_settings

负责本地模式下的系统级设置覆盖。

当前它是数据库里的全局真相层，用来覆盖：

- code defaults
- optional external project override
- `.env` 中同名的设置页可编辑 env key

适合保存：

- `models.*`
- 设置页暴露的模型、搜索、解析、观测授权
- `ingest.max_upload_size_mb`
- `ingest.max_files_per_upload`
- `planner.*`
- `docgen.allow_external_search`
- `docgen.generate_cover_image`
- `interact.history_turns`
- `rag.*`
- `local_rag.*`
- `search.retriever_profile`
- `knowledge_graph.sync_after_docgen`
- `observability.tracing_enabled`
- `observability.llm_token_summary_enabled`
- `observability.llm_observability_enabled`

### 2.4 不进入设置系统的内容

以下内容不再进入 `shared/infra/settings` 的可写配置面：

- workflow/lane 私有执行预算
- parser chain 内部常量
- search/cache/timeout/fusion 并发等低层执行参数
- LLM 并发与默认 token budget
- embedding 分批参数
- LangSmith 输入/输出截断细节

这些值应直接放回对应模块代码常量，不再通过设置页或数据库覆盖暴露。

## 3. 本地与云端

### 本地模式

- `.env` 只作为 bootstrap/default source，不由设置页写回
- `system_runtime_settings` 可写，设置页保存值逐 key 优先于 `.env`
- 只读项继续展示派生状态

### 云端模式

- 普通用户 settings 全只读
- 不存在普通用户写入 `system_runtime_settings` 的路径

## 4. 设置页展示规则

当前 settings 页面只展示后端 `/api/v1/system/settings` 返回的 section/entry 元数据。

额外约束：

- 部署级 env 仍保留在 `.env` / 部署平台变量中管理；本地设置页保存的是数据库覆盖值
- `APP_MODE`、`DATABASE_URL`、对象存储连接、底层 provider endpoint 等不再作为产品设置页字段展示
- 设置页优先承载“项目运行策略 + 常用外部服务授权”

后端是唯一真相源：

- `SettingSection.id / label / description` 决定 tab
- `SettingEntry.ui_group` 决定 tab 内分组
- `SettingEntry.ui_order` 决定稳定排序
- `SettingEntry.source / editable / secret` 决定前端控件和读写策略

前端不再维护 `tab -> key` 映射，也不再维护浏览器本机设置。

## 5. 推荐面板分区

当前最终分区为：

1. `connection`
2. `models`
3. `learning`
4. `search`
5. `observability`

每个分区内部再由后端 `ui_group` 控制展示顺序。

## 6. 一句话

现在的配置真相顺序是：

`env + code defaults + optional project override + system_runtime_settings`
