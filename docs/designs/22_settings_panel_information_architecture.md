# 22. 设置面板信息架构与变量落位设计

最后更新：2026-04-21

**状态**：规划中，未实现

本文件补充：

- `17_settings_config_ownership.md`
- `18_effective_settings_runtime.md`

这两篇文档回答的是：

- 配置归属边界是什么
- effective settings 如何合并

本文件回答的是：

- 设置面板该怎么设计，才能和当前真实配置系统对齐
- 当前各类变量该放到哪个面板位置、哪个配置层
- 哪些变量该作为常用项，哪些应进入高级项，哪些只做诊断展示
- 后端 `SettingsOverviewData` 还缺哪些 UI 元数据

---

## 1. 当前问题判断

基于当前代码，设置系统本身已经比之前清楚很多：

- 默认值集中在 `backend/app/shared/infra/settings/defaults.py`
- 运行时真相收敛到 `backend/app/shared/infra/settings/settings.py::get_settings()`
- 后端设置页数据来源集中在 `backend/app/workflows/support/system/settings.py`

但是当前设置面板仍有 4 个结构性问题。

### 1.1 面板分区和配置归属没有完全对齐

当前前端 `SettingsPanel` 的主分区是：

- `connection`
- `models`
- `learning`
- `search`
- `ops`
- `observability`

但后端返回的 section 实际是：

- `runtime`
- `models`
- `learning_engines`
- `search`
- `storage`
- `observability`

这说明前后端都在“自己理解设置分区”，还没有一份真正统一的信息架构。

### 1.2 当前面板同时混了三种不同维度

现在很多分组既按“业务领域”分，又按“技术来源”分，还夹杂“使用场景”分。

例如：

- `connection` 里同时出现浏览器本机项和后端运行状态
- `learning` 里既有 parser 偏好，也有 planner/docgen 配置，也有 KG 开关
- `observability` 里混入了 `runtime.llm_concurrency_limit` 和 `embedding.batch_*`

这会导致用户在脑内无法形成稳定心智：

```text
我是在调“学习行为”？
还是在调“部署参数”？
还是在调“浏览器临时项”？
```

### 1.3 前端大量依赖硬编码 key 集合和前缀猜分组

当前 `SettingsPanel.tsx` 里有很多类似：

- `SIMPLE_LEARNING_KEYS`
- `SIMPLE_SEARCH_KEYS`
- `SIMPLE_OBSERVABILITY_KEYS`
- `LEARNING_SETTING_PREFIXES`
- `SEARCH_SETTING_PREFIXES`
- `OBSERVABILITY_SETTING_PREFIXES`

这意味着：

- 新增配置时很容易漏改前端
- 同一个 key 应该放哪里，是靠前端猜，而不是后端声明
- “常用 / 高级”的规则没有统一真相

### 1.4 当前 source 标签也不够贴近用户心智

后端 schema 中当前 source 包括：

- `env`
- `settings`
- `system_settings`
- `user_settings`
- `runtime`

但对大多数设置页用户来说，真正关心的是：

- 这个值是**浏览器本机**的，还是**服务端全局**的？
- 是**部署级配置**，还是**运行时策略**？
- 改完是**立刻生效**，还是**要重启**？

所以仅仅告诉用户 source 还不够，还要补“作用域”和“生效方式”。

---

## 2. 设计目标

设置面板后续重构，目标不是“换个 tab 排列”，而是达成下面 6 个目标。

### 2.1 先看任务，再看变量

用户进入设置页时，不应该先面对一堆配置项名，而应该先按任务进入：

- 我想让模型换一个路由
- 我想调整上传和解析偏好
- 我想控制知识文档怎么生成
- 我想配置联网检索
- 我想检查部署和 provider 状态
- 我想做 tracing / 调试

### 2.2 先看常用项，再看高级项

设置页不应把所有变量一次性摊开。

默认应只展示：

- 直接影响日常使用体验
- 变化频率高
- 风险低
- 用户能理解其作用

而：

- 并发
- timeout
- cache
- batch
- 低层 observability

这些应进入高级视图。

### 2.3 先看可写项，再看诊断项

当前很多 section 同时包含：

- 可编辑项
- 只读状态
- 派生诊断值

推荐面板里明确分成：

- 本组可编辑项
- 当前状态
- 诊断与推导

### 2.4 让“作用域”比“来源”更清楚

每个设置项至少应该让用户一眼看懂：

1. 这是浏览器本机、服务端运行时、还是部署级变量？
2. 改完是立即生效，还是保存后建议重启？
3. 这是当前值、默认值、还是派生值？

### 2.5 前端不再自己猜分组

分区、常用/高级、控件类型、推荐说明这些 UI 元数据，应该尽量由后端返回。

### 2.6 把“变量位置”先按配置层决定，再按面板位置决定

变量应该先回答“归属到哪一层”，再回答“显示在哪个 tab / group”。

顺序不能反过来。

---

## 3. 推荐的三轴模型

后续所有设置项都建议按三条轴来规划。

### 3.1 轴一：配置层 `config layer`

这是最重要的一层。

当前推荐固定为：

1. `browser_local`
   - 当前浏览器专属
   - 不进入后端真相
2. `env`
   - 部署级、敏感、基础设施
3. `code_defaults`
   - 代码默认值
4. `project_override`
   - 可选项目级 override
5. `system_runtime_settings`
   - 本地模式下的系统级非敏感覆盖
6. `derived_runtime`
   - 派生诊断值，只读

说明：

- `code_defaults` 和 `project_override` 不必都在 UI 中直接可写
- `derived_runtime` 只负责展示，不属于“输入”

### 3.2 轴二：业务领域 `domain`

建议固定为：

1. `browser`
2. `models`
3. `ingest`
4. `planner_docgen`
5. `search_rag`
6. `knowledge_graph`
7. `deployment_integrations`
8. `observability`
9. `runtime_performance`

### 3.3 轴三：展示等级 `ui level`

建议固定为：

1. `basic`
2. `advanced`
3. `diagnostic`
4. `hidden`

含义：

- `basic`：默认展示
- `advanced`：点“显示高级”后展示
- `diagnostic`：只读状态 / 推导值
- `hidden`：不进入普通设置页

---

## 4. 推荐的面板结构

### 4.1 顶层导航建议

推荐把当前设置页收敛成 6 个顶层分区。

#### A. 当前设备

作用：

- 只放浏览器本机项
- 明确告诉用户“这些不会成为服务端真相”

建议包含：

- `apiUrl`
- `useMock`
- `debugMode`
- `mineruApiToken`

这是当前最应该从 `connection` 中单独抽出来的部分。

#### B. AI 与模型

作用：

- 所有模型路由都放这里
- 这是用户最容易主动修改的一类设置

建议包含：

- `models.primary`
- `models.reason`
- `models.light`
- `models.extract`
- `models.embedding`
- `models.ocr`
- `models.image_generation`

诊断项：

- `models.embedding_dim`

不建议放这里：

- provider API key
- 并发限制

#### C. 学习构建

这是最重要的业务页。

它应再分成 4 个子组：

1. 上传与解析
   - `ingest.*`
2. 规划策略
   - `planner.*`
3. 知识文档生成
   - `docgen.*`
4. 伴读与图谱联动
   - `interact.history_turns`
   - `knowledge_graph.sync_after_docgen`

当前 `learning_engines` 一整坨混在一起，建议就按这个层级重新排。

#### D. 检索与来源

只放和资料检索、联网、RAG、reader 相关的运行策略。

建议包含：

- `local_rag.*`
- `rag.*`
- `search.retriever_profile`
- `search.retrievers`
- `search.max_results_per_query`

高级项：

- provider / total / read timeout
- 并发 provider
- fusion_k
- runtime cache

诊断项：

- `search.retriever_profiles`
  当前仍建议只读展示，不做普通表单编辑。

#### E. 部署与集成

当前 `connection` + `ops` + 部分 runtime 状态，建议收敛到这里。

建议包含：

- APP_MODE / mode
- auth enabled
- settings source
- DATABASE_URL
- 存储后端
- S3 / DogeCloud 状态
- 关键 provider 是否已配置

这里默认以只读状态页为主。

本地模式下可写：

- `.env` 中允许的部署级变量

#### F. 观测与性能

当前 `observability` 里混了 observability 和 performance，建议明确合并到一页，但分成两个子组：

1. 观测
   - tracing
   - langsmith capture
   - token summary
   - max records
2. 运行时性能
   - `runtime.llm_concurrency_limit`
   - `runtime.default_token_budget`
   - `embedding.batch_size`
   - `embedding.batch_delay_s`

这样至少不会再把并发限制误读成“观测开关”。

---

## 5. 各类变量推荐落位

本节是后续真正改 UI 时最有用的部分。

### 5.1 浏览器本机项

这些变量的归属非常明确，应该单独放在“当前设备”。

| 变量 | 配置层 | 面板位置 | 说明 |
| --- | --- | --- | --- |
| `apiUrl` | `browser_local` | 当前设备 / 连接 | 当前浏览器请求的后端地址 |
| `useMock` | `browser_local` | 当前设备 / 开发 | 当前浏览器是否启用 Mock |
| `debugMode` | `browser_local` | 当前设备 / 调试 | 当前浏览器调试体验开关 |
| `mineruApiToken` | `browser_local` | 当前设备 / 临时凭证 | 临时覆盖上传时使用的 MinerU Token |

结论：

- 不要再和服务端连接状态混在同一个 section 顶层
- 这组变量应该被明确标记为“仅当前浏览器”

### 5.2 模型路由

这些变量最适合集中放在“AI 与模型”。

| 变量 | 配置层 | UI 等级 | 建议位置 |
| --- | --- | --- | --- |
| `models.primary` | `system_runtime_settings` | `basic` | AI 与模型 / 核心路由 |
| `models.reason` | `system_runtime_settings` | `basic` | AI 与模型 / 核心路由 |
| `models.light` | `system_runtime_settings` | `basic` | AI 与模型 / 核心路由 |
| `models.extract` | `system_runtime_settings` | `advanced` | AI 与模型 / 专用模型 |
| `models.embedding` | `system_runtime_settings` | `basic` | AI 与模型 / 向量模型 |
| `models.ocr` | `system_runtime_settings` | `advanced` | AI 与模型 / 专用模型 |
| `models.image_generation` | `system_runtime_settings` | `advanced` | AI 与模型 / 专用模型 |
| `models.embedding_dim` | `derived_runtime` | `diagnostic` | AI 与模型 / 运行推导 |
| `models.overrides` | `code_defaults/project_override` | `hidden` | 不进普通面板 |

结论：

- `models.overrides` 继续不要进普通 UI
- `embedding_dim` 只读展示即可

### 5.3 上传与解析

建议全部放在“学习构建 -> 上传与解析”。

#### 常用

- `ingest.default_parser_provider`
- `ingest.mineru_model_version`
- `ingest.mineru_enable_formula`
- `ingest.mineru_enable_table`
- `ingest.mineru_is_ocr`

#### 高级

- `ingest.max_upload_size_mb`
- `ingest.max_files_per_upload`
- `ingest.parse_concurrency`
- `ingest.parser_timeout_s`

#### 部署级补充

- `MINERU_API_TOKEN`

建议不直接混在同一组表单里，而是：

- 运行时偏好放“学习构建”
- 服务端 `.env` 凭证放“部署与集成 -> 文档解析服务”

### 5.4 Planner 与 DocGen

这组变量最适合合并成“学习构建”的核心页。

#### Planner 子组

基础：

- `planner.default_digest_mode`
- `planner.sprint.min_chapters`
- `planner.sprint.max_chapters`
- `planner.sprint.target_length`
- `planner.systematic.min_chapters`
- `planner.systematic.max_chapters`
- `planner.systematic.target_length`

说明：

- 这是非常典型的“教学策略参数”
- 不应该和 `ingest` 或 `search` 混在一起

#### DocGen 子组

基础：

- `docgen.allow_external_search`
- `docgen.generate_cover_image`

高级：

- `docgen.max_parallel_chapters`
- `docgen.io_parallelism`
- `docgen.max_research_queries`
- `docgen.retrieval_timeout_s`
- `docgen.read_timeout_s`

说明：

- `allow_external_search` 更像“教学来源策略”，但从用户心智上仍然与 DocGen 更相关
- `generate_cover_image` 更像“文档表现增强”，适合放在 DocGen 的“输出形态”分组

### 5.5 Interact 与 Knowledge Graph

当前这两个变量数量不多，不值得单独开顶层页。

建议放在“学习构建”页底部的“联动行为”小组：

- `interact.history_turns`
- `knowledge_graph.sync_after_docgen`

高级保留：

- `knowledge_graph.extract_max_parallelism`

如果未来 Knowledge Graph 配置变多，再考虑拆页。

### 5.6 检索与来源

这组变量建议按“策略 / 高级调优 / Provider 状态”三层分。

#### 常用策略

- `local_rag.priority`
- `local_rag.min_results`
- `rag.top_k`
- `rag.similarity_threshold`
- `rag.rerank_model`
- `rag.rerank_top_k`
- `search.retriever_profile`

#### 高级调优

- `search.retrievers`
- `search.max_results_per_query`
- `search.scrape_timeout_s`
- `search.provider_timeout_s`
- `search.total_timeout_s`
- `search.read_timeout_s`
- `search.parallel_retrievers`
- `search.max_parallel_retrievers`
- `search.fusion_k`
- `search.runtime_cache_enabled`
- `search.runtime_cache_ttl_s`
- `search.runtime_cache_max_entries`

#### Provider / 凭证状态

全部 `.env` 项，包括：

- `TAVILY_API_KEY`
- `BRAVE_SEARCH_API_KEY`
- `EXA_API_KEY`
- `BING_API_KEY`
- `BOCHA_API_KEY`
- `JINA_API_KEY`
- `SERPER_API_KEY`
- `PERPLEXITY_API_KEY`
- `OPENROUTER_API_KEY`
- `BAIDU_AI_SEARCH_API_KEY`
- `GOOGLE_API_KEY`
- `GOOGLE_CX_KEY`
- `SEARCHAPI_API_KEY`
- `SERPAPI_API_KEY`
- `NCBI_API_KEY`
- `MCP_SEARCH_TOOL`
- `SEARXNG_BASE_URL`
- `JINA_READER_ENABLED`
- `RAG_RERANK_API_KEY`

结论：

- 这些 provider 项绝不应默认铺满在检索页一屏里
- 默认应收进“Provider 状态”
- 本地模式再支持点击展开编辑

### 5.7 部署与集成

建议把下面这些都收进“部署与集成”，而不是继续散落在 connection / ops：

#### 运行模式与鉴权

- `runtime.mode`
- `runtime.app_mode_raw`
- `runtime.version`
- `auth.enabled`
- `settings.source`

#### 数据库与存储

- `DATABASE_URL`
- `storage.backend`
- `S3_BUCKET`
- `S3_ENDPOINT`
- `S3_PUBLIC_BASE_URL`
- `storage.s3_addressing_style`
- `storage.s3_credential_mode`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `DOGECLOUD_API_ACCESS_KEY`
- `DOGECLOUD_SPACE_NAME`

这里建议默认是状态页：

- 已配置 / 未配置
- 当前后端值
- 当前生效推导

本地模式才允许对 `.env` 写入。

### 5.8 观测与性能

建议明确拆成两个子组。

#### 观测

- `observability.tracing_enabled`
- `observability.llm_token_summary_enabled`
- `observability.timing_top_k`
- `observability.langsmith_capture_inputs`
- `observability.langsmith_capture_outputs`
- `observability.langsmith_max_text_chars`
- `observability.llm_observability_enabled`
- `observability.llm_observability_max_records`
- `LANGSMITH_TRACING`
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `LANGSMITH_ENDPOINT`

#### 性能

- `runtime.llm_concurrency_limit`
- `runtime.default_token_budget`
- `embedding.batch_size`
- `embedding.batch_delay_s`

结论：

- 这几项应从“观测”重命名为“观测与性能”
- 避免误导用户以为并发和 embedding 批处理属于 trace 设置

---

## 6. 建议从“按 source 显示”改成“按任务 + 作用域显示”

当前 source badge 仍然保留价值，但它不应该成为主分组依据。

推荐在每个设置项上补两个视觉标记：

1. `作用域`
   - 浏览器
   - 服务端运行时
   - 部署级
   - 派生值

2. `生效方式`
   - 立即生效
   - 保存后建议重启
   - 只读诊断

而 source label 可以收敛成更偏技术口径的次级信息。

---

## 7. 推荐的后端 UI 元数据扩展

要真正摆脱前端硬编码 key 分组，建议给 `SettingEntry` 增加最少一组 UI 元数据。

### 7.1 推荐新增字段

建议新增：

```text
ui_section
ui_group
ui_order
ui_level
ui_control
scope
effect
options
```

含义建议：

- `ui_section`
  - 顶层页，例如 `browser` / `models` / `learning` / `search` / `deployment` / `observability`
- `ui_group`
  - 组内分块，例如 `planner` / `docgen` / `provider_keys`
- `ui_order`
  - 排序
- `ui_level`
  - `basic / advanced / diagnostic / hidden`
- `ui_control`
  - `text / password / select / switch / readonly`
- `scope`
  - `browser_local / env / runtime_override / derived`
- `effect`
  - `immediate / restart_recommended / readonly`
- `options`
  - select 的可选项

### 7.2 当前 schema 最小可行升级

如果不想一次加太多字段，第一步至少加：

```text
ui_section
ui_group
ui_level
scope
effect
```

只要这 5 个到位，前端就可以把绝大多数硬编码集合删掉。

---

## 8. 推荐的显示规则

### 8.1 默认显示规则

默认页面只展示：

- `ui_level = basic`
- `editable = true`
- 当前模式允许编辑

### 8.2 高级显示规则

点击“显示高级”后再展示：

- `ui_level = advanced`

### 8.3 诊断显示规则

诊断项不跟高级项混在一起。

推荐固定在每个页面底部的：

- “当前状态”
- “运行推导”
- “Provider 状态”

区域显示。

### 8.4 隐藏项

以下类型继续不建议进普通设置面板：

- `models.overrides`
- `search.retriever_profiles` 的原始编辑
- project override 文件路径本身的表单编辑
- 未来任何“内部兼容字段”或“实验字段”

---

## 9. 近期最值得做的改动顺序

### Step 1：先统一信息架构，不急着大改样式

优先做：

- 明确顶层 6 个分区
- 把浏览器本机项从 `connection` 里抽出来
- 把 `observability` 重构成“观测与性能”
- 把 `learning_engines` 拆成 ingest / planner / docgen / 联动小组

### Step 2：后端开始返回最少 UI 元数据

优先新增：

- `ui_section`
- `ui_group`
- `ui_level`
- `scope`
- `effect`

### Step 3：删掉前端大部分硬编码 key 集合

后续 `SettingsPanel.tsx` 不应再维护一大堆：

- `SIMPLE_*_KEYS`
- `*_PREFIXES`

而应直接按后端返回的 UI 元数据渲染。

### Step 4：把 provider / env 大量凭证项折叠成状态卡

这一步会极大改善设置页的可读性。

### Step 5：补“变量位置说明”

每个设置项 hover 或副文案里补：

- 这是浏览器项 / 运行时项 / 部署项
- 是否会写 `.env`
- 是否会写 `system_runtime_settings`
- 是否建议重启

---

## 10. 一句话结论

当前设置面板最需要的，不是再微调几个 tab，而是先收敛成一套稳定原则：

```text
变量先按配置层归属
再按业务任务分区
最后再决定是否进入常用 / 高级 / 诊断
```

更具体一点：

> **浏览器本机项独立、模型独立、学习构建独立、检索独立、部署独立、观测与性能独立；而分组与展示等级应由后端元数据声明，不再由前端靠 key 猜。**
