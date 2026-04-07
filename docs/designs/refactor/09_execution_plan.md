## 九、分阶段重构执行计划

### 9.1 总体原则

- **渐进式重构**：每个阶段都能独立运行和测试，不会出现"改了一半跑不起来"的情况
- **向后兼容**：旧 API 接口不变，前端无感知
- **LangSmith 先行**：每个新模块第一天就接入 LangSmith，不留"后补"的债
- **测试驱动**：每个节点都有独立的单元测试（mock LLM 调用）

### 9.2 Phase 0：基础设施层（预计 2-3 天）

**目标**：扩展 model_router + 新建检索/抓取基础设施，不动任何 workflow 代码。

| 任务 | 涉及文件 | 验证方式 |
|:---|:---|:---|
| 1. `llm_support/fallback.py` 新增 `acompletion_with_fallback()` | `shared/infra/llm_support/fallback.py` | 单元测试：验证 TaskType 降级链正确路由 |
| 2. `config.py` 确认 `model_overrides` 支持 docgen 差异化配置 | `shared/infra/config.py` | 无需改动（已有机制），只需在 .env 中配置 |
| 3. `.env` 新增差异化模型配置（可选） | `.env` | 不配等于不启用，向后兼容 |
| 4. 确认 `llm_support/observability.py` 自动记录 `task_type` | `shared/infra/llm_support/observability.py` | LangSmith 中能看到 task_type 标签 |
| 5. 新建 `shared/infra/search/retrievers/base.py` + `factory.py` | `shared/infra/search/` | 工厂函数能正确实例化 |
| 6. 新建 `shared/infra/search/retrievers/bing.py` | `shared/infra/search/retrievers/` | 集成测试：能搜到结果 |
| 7. 新建 `shared/infra/search/retrievers/duckduckgo.py` | `shared/infra/search/retrievers/` | 集成测试：能搜到结果 |
| 8. 新建 `shared/infra/search/retrievers/local_rag.py` | `shared/infra/search/retrievers/` | 封装现有 `search_knowledge()` |
| 9. 新建 `shared/infra/search/scraper/` (bs4 + pdf) | `shared/infra/search/scraper/` | 集成测试：能抓取网页/PDF |

**风险控制**：这个阶段只新增一个文件 `fallback.py`，不修改任何现有文件的签名或行为。不配 `model_overrides` 时所有流程行为完全不变。

### 9.3 Phase 1：Skills + Actions 层（预计 2-3 天）

**目标**：实现核心 Skill 类和 Action 函数，可独立测试。

| 任务 | 涉及文件 | 验证方式 |
|:---|:---|:---|
| 1. `skills/base.py` 新增 `BaseSkill` + `SkillContext` + `SkillResult` | `shared/infra/skills/base.py` | 不破坏现有 `@skill` 装饰器 |
| 2. 实现 `skills/context_manager.py` | `shared/infra/skills/context_manager.py` | 单元测试：压缩效果验证 |
| 3. 实现 `skills/researcher.py` | `shared/infra/skills/researcher.py` | 集成测试：搜索 + 抓取 + 压缩 |
| 4. 实现 `tools/builtin/query_processing.py` | `shared/infra/tools/builtin/` | 单元测试：子查询生成 |
| 5. 实现 `tools/builtin/web_scraping.py` | `shared/infra/tools/builtin/` | 集成测试：URL 抓取 |
| 6. 实现 `tools/builtin/markdown_processing.py` | `shared/infra/tools/builtin/` | 单元测试：占位符处理 |
| 7. 实现 `tools/builtin/latex_processing.py` | `shared/infra/tools/builtin/` | 单元测试：LaTeX 校验 |

**风险控制**：所有新 Skill/Action 都是独立模块，不影响现有 workflow。

### 9.4 Phase 2：DocGen 流程重建（预计 3-5 天，核心阶段）

**目标**：重写 Docs Lane 的 LangGraph 拓扑和所有节点。

| 任务 | 涉及文件 | 验证方式 |
|:---|:---|:---|
| 1. 重写 `docgen/state.py` | `workflows/digest/docgen/state.py` | 类型检查通过 |
| 2. 新建 `nodes/edu_planner_node.py` | `workflows/digest/docgen/nodes/` | 单元测试：输出合法 JSON |
| 3. 新建 `nodes/targeted_research_node.py` | `workflows/digest/docgen/nodes/` | 集成测试：搜索 + 压缩 |
| 4. 新建 `nodes/pedagogy_craft_node.py` | `workflows/digest/docgen/nodes/` | 集成测试：生成 Markdown |
| 5. 新建 `nodes/enrich_document_node.py` | `workflows/digest/docgen/nodes/` | 集成测试：占位符替换 |
| 6. 新建 `nodes/inject_examine_node.py` | `workflows/digest/docgen/nodes/` | 集成测试：生成考题 |
| 7. 改造 `nodes/load_files_node.py` → `load_context_node.py` | `workflows/digest/docgen/nodes/` | 兼容现有 shared_inputs |
| 8. 改造 `nodes/finalize_node.py` | `workflows/digest/docgen/nodes/` | 兼容现有存储逻辑 |
| 9. 重写 `docgen/graph.py` | `workflows/digest/docgen/graph.py` | `langgraph dev` 能跑通 |
| 10. 重写 `prompts/` (sprint + systematic) | `workflows/digest/docgen/prompts/` | Prompt 审阅 |
| 11. 适配 `observability.py` 的 docs lane summary | `workflows/digest/observability.py` | LangSmith 中能看到新节点 |
| 12. 适配 `runtime.py` 的 docgen 入口 | `workflows/digest/runtime.py` | 端到端测试 |

**关键里程碑**：Phase 2 完成后，用 `langgraph dev` 跑一次完整的 DocGen 流程（输入"偏导数"），在 LangSmith 中验证完整 trace 树。

### 9.5 Phase 3：富媒体增强（预计 2-3 天）

| 任务 | 涉及文件 | 验证方式 |
|:---|:---|:---|
| 1. 实现 `skills/image_generator.py` | `shared/infra/skills/` | 集成测试：生成图片 |
| 2. 实现 `skills/mermaid_generator.py` | `shared/infra/skills/` | 单元测试：生成合法 Mermaid |
| 3. 前端 Mermaid 渲染组件 | `frontend/src/components/` | 页面能渲染 Mermaid |
| 4. 前端 KaTeX 公式渲染优化 | `frontend/src/components/` | 复杂公式能正确渲染 |
| 5. 前端文档阅读页面改版 | `frontend/src/pages/` | 支持富媒体文档展示 |

### 9.6 Phase 4：教育资源库 + 高级功能（预计 3-5 天）

| 任务 | 涉及文件 | 验证方式 |
|:---|:---|:---|
| 1. 构建本地教育语料库 | `data/edu_corpus/` | 向量检索能命中 |
| 2. 实现 `skills/source_curator.py` | `shared/infra/skills/` | 来源质量评估 |
| 3. 教育 Teaching Skills 实现 | `shared/infra/skills/` | Skill 可被 LLM 调用 |
| 4. 交互式 HTML 支持（V2 预留） | `shared/infra/skills/interactive_builder.py` | 接口定义 + stub 实现 |
| 5. Anki 导出功能（V2 预留） | `shared/infra/tools/builtin/` | 接口定义 + stub 实现 |

### 9.7 性能目标

| 节点 | 目标延迟 | 并发度 | Token 预算 |
|:---|:---|:---|:---|
| `edu_planner` | < 15s | 1（串行） | REASONING: 4000 |
| `targeted_research` × N | < 20s（含搜索+抓取+压缩） | N=章节数，受 `docgen_max_parallel_chapters` 控制（默认 20） | DOCGEN_LIGHT: 3000/章 |
| `pedagogy_craft` × N | < 30s/章 | 同上 | DOCGEN: 8000/章 |
| `enrich_document` | < 15s | 图片并行生成（max 3） | DOCGEN_LIGHT: 1000 |
| 端到端（速成课 4 章） | **< 2 分钟** | — | — |
| 端到端（系统课 8 章） | **< 5 分钟** | — | — |

> [!TIP]
> 性能对标参考：gpt-researcher 标准研究流程 1-3 分钟（3 个子查询）。我们的速成课 4 章并发等效于 4 个子查询，性能预期应与其相当。

### 9.8 缓存策略

| 缓存对象 | Key | TTL | 后端 |
|:---|:---|:---|:---|
| `edu_planner` 输出 | `(subject, digest_mode, tone)` | 24h | 内存 dict（MVP），后续切 Redis |
| 检索结果 | `(query, retriever_name)` | 1h | 内存 dict |
| 网页抓取结果 | URL | 24h | 内存 dict |
| Embedding 向量 | `(text_hash, model)` | 永久 | sqlite-vec（已有） |

**缓存失效策略**：
- 用户上传新文件后，该 subject 的 `edu_planner` 缓存立即失效
- 超过 TTL 的缓存惰性清理（下次访问时检查）

### 9.9 回滚策略

| 阶段 | 回滚机制 |
|:---|:---|
| Phase 0 | 纯新增 `fallback.py`，不改旧代码 → 零风险 |
| Phase 1 | 新 Skill/Action 独立模块 → 删除即回滚 |
| Phase 2 | 保留旧 `graph.py` 为 `graph_legacy.py`，通过 feature flag `DOCGEN_USE_NEW_PIPELINE=true` 切换 |
| Phase 3/4 | 纯新增 → 删除即回滚 |

**Feature Flag 配置**：
```env
# .env 新增
DOCGEN_USE_NEW_PIPELINE=false    # Phase 2 完成前默认 false
```

在 `runtime.py` 中根据 flag 选择 graph builder：
```python
if get_settings().docgen_use_new_pipeline:
    graph = build_docgen_graph(context=context)       # 新版
else:
    graph = build_docgen_graph_legacy(context=context) # 旧版
```

Phase 2 验证通过后将默认值改为 `true`，v2.0 正式发布时删除 `graph_legacy.py`。

### 9.10 测试策略

| 测试类型 | 范围 | 工具/方法 |
|:---|:---|:---|
| **单元测试** | 每个节点 mock LLM 调用，验证输入输出格式 | pytest + unittest.mock |
| **集成测试** | 用 `langgraph dev` 跑完整流程，验证 trace 树 | langgraph dev + LangSmith |
| **质量测试** | 生成 "偏导数" 速成课 + 系统课各一份，人工评审 | 人工评审 checklist |
| **性能测试** | 计时端到端延迟，对比 9.7 性能目标 | pytest-benchmark / 手动 |
| **回归测试** | 切换 feature flag 验证旧流程不受影响 | pytest |

**质量评审 checklist**：
- [ ] 章节结构符合 05_document_modes.md 定义
- [ ] LaTeX 公式正确渲染
- [ ] Mermaid 思维导图语法合法
- [ ] 速成课包含秒杀口诀 + 范例题
- [ ] 系统课字数 ≥ 10000
- [ ] 所有引用有来源 URL

---
