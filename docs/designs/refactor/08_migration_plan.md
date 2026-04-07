## 八、要删除 / 废弃的旧文件清单

### 8.1 Docs Lane 废弃文件

以下是当前 `docgen/` 中将在重构后**不再需要**的文件：

| 文件 | 原来的功能 | 被什么替代 | 处理方式 |
|:---|:---|:---|:---|
| `nodes/cleanse_node.py` | 文本清洗（LLM 自愈） | `targeted_research` 中的 ContextCompressor 自带降噪 | 删除 |
| `nodes/outline_map_node.py` | 从 chunks 提取局部大纲 | `edu_planner` 统一规划（不依赖原文结构） | 删除 |
| `nodes/outline_reduce_node.py` | 合并局部大纲为全局大纲 | `edu_planner` 统一规划 | 删除 |
| `nodes/review_node.py` | 章节审阅 | 取消独立 review（质量由 Planner + Research 前置保障） | 删除 |
| `nodes/metadata_node.py` | 元数据提取 | 合并进 `finalize_assemble` | 删除 |
| `strategy.py` | 旧版执行策略（CleanseDecision / OutlineExecutionPlan / ReviewExecutionPlan） | 新版 strategy 只保留 `chapter_semaphore` + `io_semaphore` | 重写 |
| `prompts/docgen_prompts.py` | 旧版 Prompt | 全部重写为教育极性 Prompt（速成/系统双模式） | 重写 |

### 8.2 保留并复用的文件

| 文件 | 原来的功能 | 复用方式 |
|:---|:---|:---|
| `nodes/load_files_node.py` | 加载用户文件 chunks | 改名为 `load_context_node.py`，逻辑基本不变 |
| `nodes/draft_node.py` | 章节写作 | 重写为 `pedagogy_craft_node.py`，复用 `write_chapter()` 服务的调用模式 |
| `nodes/finalize_node.py` | 组装入库 | 保留，扩展支持富媒体字段 |
| `state.py` | DocGenState 定义 | 重写（新增字段，保留输出字段兼容） |
| `graph.py` | LangGraph 拓扑 | 重写（新拓扑） |
| `services/writer_service.py` | LLM 写作服务 | 保留，扩展支持双模式 Prompt |

### 8.3 新增文件清单

| 文件 | 功能 |
|:---|:---|
| `nodes/edu_planner_node.py` | 教研大纲规划节点 |
| `nodes/targeted_research_node.py` | 靶向素材搜刮节点 |
| `nodes/pedagogy_craft_node.py` | 教学化写作节点 |
| `nodes/enrich_document_node.py` | 富媒体增强节点 |
| `nodes/inject_examine_node.py` | 联动出题节点 |
| `prompts/sprint_prompts.py` | 速成课 Prompt 集 |
| `prompts/systematic_prompts.py` | 系统课 Prompt 集 |

### 8.4 迁移时间线与策略

| 阶段 | 动作 | 备注 |
|:---|:---|:---|
| Phase 0 完成 | 无文件删除 | 仅新增 `llm_support/fallback.py`（`acompletion_with_fallback`），不影响旧代码 |
| Phase 1 完成 | 无文件删除 | 新 Skill/Action 独立模块，旧代码照常运行 |
| Phase 2 开始 | 旧 `graph.py` 复制为 `graph_legacy.py` | Feature flag `DOCGEN_USE_NEW_PIPELINE=false` 保护 |
| Phase 2 完成 | 翻转 flag 为 `true` | 内部测试 2 天后正式切换 |
| Phase 2 + 1 周 | 删除 `graph_legacy.py` + 8.1 中的废弃文件 | 确认无回滚需求后执行 |
| Phase 3/4 完成 | 无额外删除 | 纯新增功能 |

**关键说明**：
- `DocGenState` **无需数据迁移**：State 是 LangGraph 运行时对象，不持久化到 DB。新旧 State 定义互不影响
- 删除旧节点文件前，确认 `observability.py` 的 `build_docs_lane_summary()` 已适配新节点名（参见 04 文档 4.7 节字段映射表）

### 8.5 废弃的配置参数（Phase 2 完成后删除）

以下 `config.py` 中的参数与**旧 DocGen 流程**绑定，在新流程中不再需要：

| 参数 | 旧用途 | 新流程替代 | 处理方式 |
|:---|:---|:---|:---|
| `docgen_skip_llm_cleanse_for_clean_markdown` | 跳过 cleanse 节点 | 新流程无 cleanse 节点 | 删除 |
| `docgen_skip_llm_review_for_single_chapter` | 跳过 review 节点 | 新流程无 review 节点 | 删除 |
| `docgen_outline_fast_path_max_chunks` | outline 快速路径判断 | 新流程 edu_planner 不依赖 chunks 数 | 删除 |
| `docgen_review_retry_mode` | review 重试模式 | 新流程无 review | 删除 |
| `docgen_review_fast_path_max_chapters` | review 快速路径判断 | 新流程无 review | 删除 |
| `docgen_metadata_fallback_llm` | metadata 提取降级 | 合并到 `finalize_assemble` 内部逻辑 | 删除 |

**保留的参数**：
- `docgen_max_parallel_chapters` → 沿用，对应新流程的 `chapter_semaphore`
- `docgen_io_parallelism` → 沿用，控制文件 I/O 并行度

### 8.6 架构层面已完成的清理

| 改动 | 说明 |
|:---|:---|
| `subject_embeddings.py` → `subject_settings.py` | 重命名为更准确的名称，旧文件已删除 |
| `infra/context.py` → `teaching/context.py` | 教学上下文逻辑归入 `teaching/` 包，infra 旧文件已删除 |
| `infra/teaching.py` → `teaching/teaching.py` | 教学函数逻辑归入 `teaching/` 包，infra 旧文件已删除 |

---
