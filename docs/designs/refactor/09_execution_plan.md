## 九、分阶段执行计划

> 目标：把重构拆成可以逐阶段上线、逐阶段验证、逐阶段回滚的计划，而不是一次性大改。  
> 最后更新：2026-04-09

---

## 9.1 总体策略

### 先做什么

- 先冻结分层边界与观测契约
- 再升级 Docs Lane 的 research 和写作质量
- 最后再补富媒体、教学工具、教育语料库

### 明确不做什么

- 不同步重写五大引擎
- 不为了迁移 `gpt-researcher` 而复制目录树
- 不在没有 LangSmith 可视化的前提下盲改主流程

### 总原则

1. 只要一个阶段结束，就应该是“可运行、可观测、可回退”的。
2. 所有实质性行为改动优先限制在 `planner/docgen`。
3. 所有阶段都要验证不会破坏 KG Lane 和其他四个引擎。

---

## 9.2 Phase 0：边界冻结与文档对齐

### 目标

先把未来所有改动的设计地基打稳。

### 范围

- `docs/designs/refactor/*`
- `docs/designs/10_repo_structure_and_runtime_files.md`

### 要完成的事

- 明确 `shared/infra`、`teaching`、`workflows` 的职责
- 明确 canonical memory 在 `shared/infra/memory`
- 明确 `teaching/memory` 仅为过渡层
- 明确 `sprint` / `systematic` 的输出契约
- 明确 LangSmith 命名与 metadata 口径

### 验收标准

- 后续新代码能够根据文档直接判断放哪层
- 不再出现“教学逻辑写回 workflow”“第二套 memory 实现”这类模糊地带

---

## 9.3 Phase 1：LangSmith 与运行时契约加固

### 目标

让 Planner、DocGen、Asset、Examine 注入都能在 LangSmith 里串起来。

### 主要改动

- 统一 `build_session_id / planner_session_id / confirmed_plan_id`
- 增加 `course_type / retrieval_profile / asset_kind / teaching_action` 等 metadata
- 打通前端进度事件与 LangSmith 节点语义

### 只允许改动

- `workflows/common`
- `workflows/digest/observability.py`
- `planner` / `docgen` 相关 state 与 event
- 相关 skill 的 trace metadata

### 验收标准

- 打开 LangSmith 后，能一眼看到 Planner → DocGen 的关联
- 每章 research / writing / enrich / examine 都能单独定位

---

## 9.4 Phase 2：检索 profile 与工具基座加固

### 目标

把“什么场景用什么检索组合”从隐式逻辑变成显式 profile。

### 主要改动

- 引入 `planner_grounding` / `docgen_sprint` / `docgen_systematic` / `media_hunting`
- 增加检索结果缓存和抓取缓存
- 补齐高价值检索器与高质量抓取策略
- 停止继续扩散平行工具实现

### 关键目录

- `shared/infra/search`
- `shared/infra/tools`
- `shared/infra/skills/researcher.py`

### 验收标准

- 同一查询不再反复裸搜
- `sprint` 与 `systematic` 在 LangSmith 上呈现不同的检索 profile
- ResearchConductor 的输出能带出清晰的来源分类

---

## 9.5 Phase 3：Digest 研究链升级

### 目标

让当前章节 research 从“一次性搜一轮”升级为“轻量质量驱动研究”。

### 主要改动

- Planner 输出稳定的 `Build Contract`
- `targeted_research` 内部加入章节级 research 微循环
- `PedagogyWriter` 输出更稳定的章节结构信息
- 章节草稿不再只是一段自由 Markdown

### 关键约束

- 先把 deep research 风格的“补缺口”做在 skill 内部
- 不要急着把 graph 拆成十几个节点
- 保持 Docs Lane 图在 LangSmith 中依然清楚

### 验收标准

- `sprint` 章节更像冲刺讲义
- `systematic` 章节更像课程讲义
- 章节 research 可以解释“为什么还要再补一轮”

---

## 9.6 Phase 4：富媒体与课程呈现升级

### 目标

让知识文档不只是“长 Markdown”，而是可持续增强的课程产物。

### 主要改动

- 引入显式 `asset_plan`
- 完善 Mermaid / image / interactive HTML 插槽
- 丰富章节 recap、公式卡、错因卡、导览块
- 优化发布时的资源落盘与 manifest

### 关键目录

- `shared/infra/skills/image_generator.py`
- `shared/infra/skills/mermaid_generator.py`
- `app.teaching.documents`
- 前端阅读页面与 MarkdownViewer

### 验收标准

- 文档富媒体增强不破坏正文主线
- 发布后的文档和资源能稳定追踪
- 前端渲染表现明显优于“原始 Markdown 列表页”

---

## 9.7 Phase 5：Teaching 闭环接入

### 目标

把 `examine`、`profile` 的结果真正翻译成教学表达和文档增强。

### 主要改动

- 建设教学解释类 tool / adapter
- 把弱点、错因、学习建议接到 DocGen 与 Interact
- 形成“知识文档 -> 练习 -> 画像 -> 再次文档增强”的闭环

### 关键目录

- `app.teaching`
- `workflows/digest/docgen`
- `workflows/interact`
- `workflows/examine`
- `workflows/profile`

### 验收标准

- 文档可以根据用户画像呈现不同的强调点
- 练习反馈不只是判分，而是能回流成教学建议

---

## 9.8 Phase 6：教育语料库与评测

### 目标

让系统具备自己的高质量教育底仓和稳定评测手段。

### 主要改动

- 建立最小可用教育语料库
- 定义文档质量评测样本
- 建立速度 / 质量 / 成本三类 Dashboard

### 关键目录

- `backend/data/edu_corpus/`
- `docs/designs/refactor/10_langsmith_observability.md`
- 相关评测脚本与样本集

### 验收标准

- 没有上传资料时，依然能生成有质量的系统课
- 可以量化比较不同 prompt / profile / asset 策略的效果

---

## 9.9 关键里程碑与风险控制

### 里程碑 1

边界冻结完成后，任何新能力都能明确放层。

### 里程碑 2

Planner 与 DocGen 的 trace 串联完成后，主流程具备可持续优化能力。

### 里程碑 3

课程模式契约稳定后，生成质量才会真正可控。

### 里程碑 4

富媒体资产与教学闭环接入后，知识文档才会显著区别于通用 deep research。

---

## 9.10 每个阶段都要验证的四件事

1. 不影响 `ingest / interact / examine / profile` 的主流程。
2. 不破坏 `digest/kg` 与 `digest/curriculum`。
3. LangSmith 图是否仍然一眼能看懂。
4. 前端是否还能稳定展示当前文档产物。

---

## 9.11 一句话结论

这轮重构最怕的不是“做得慢”，而是“边界没立住就乱改”。  
正确路径是：先冻结边界，再升级 research，再升级呈现，最后接教学闭环与语料库。
