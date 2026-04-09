## 七、Teaching Tools 与教学能力落位

> 目标：明确哪些能力属于通用工具，哪些能力属于教学工具，避免 `infra` 和 `teaching` 再次长出平行实现。  
> 最后更新：2026-04-09

---

## 7.1 先回答当前最核心的问题

### “`infra` 里放通用工具，`teaching` 里放教学相关工具，合理吗？”

合理。  
但要满足下面这条前提：

> **`infra` 负责接口、抽象、策略和统一 runtime；`teaching` 负责 AITeachMe 教学任务适配和教学表达。**

如果 `teaching` 开始复制：

- memory store
- retriever
- tool registry
- LLM provider
- runtime path

那这就不再是合理分层，而是形成第二套底座。

---

## 7.2 三层职责

### 7.2.1 `shared/infra`

负责：

- 通用 tool / skill / search / scraper / tracing / memory / storage
- 第三方 API 接入
- 统一输入输出与错误语义
- 可替换接口、基类、工厂与策略

这里关注的是：

- 功能能不能稳定调用
- 结果能不能复用
- LangSmith 能不能看清
- 能力是否足够抽象，能被多个教学场景复用

### 7.2.2 `teaching`

负责：

- 把通用能力翻译成 AITeachMe 的教学任务
- 学习者视角的解释方式
- 教学脚手架
- 教学块与文档结构
- 错因翻译、学习建议、习题讲评
- 针对不同课程模式的教学表达

这里关注的是：

- 这是不是“在教”
- 这是不是更容易学
- 这是不是更符合考试或课程场景
- 这是不是符合我们的产品理念和教学方法

### 7.2.3 `workflows`

负责：

- 什么时候调用哪些 teaching / infra 能力
- 状态如何推进
- 并发与错误如何处理

---

## 7.3 教学能力应该怎么分级

### A. 通用底层工具

这些不属于教学专属：

- 网页搜索
- 抓取
- Markdown / LaTeX 处理
- memory 读写
- 内容分析
- 图像生成
- Mermaid 生成

建议落点：

- `shared/infra/tools`
- `shared/infra/skills`

### B. 教学适配器

这些是“把通用能力翻译成教学动作”：

- 解释一个概念
- 用大白话翻译公式
- 对比两个易混概念
- 给出章节导读
- 把错题诊断翻译成学习建议

建议落点：

- `app.teaching`

这里最关键的不只是“写几个模板”，而是把任务级判断沉下来：

- 这章该怎么教
- 冲刺课该强调什么
- 系统课该展开什么
- 这类错题应该怎样解释才符合 AITeachMe 的教学目标

### C. 教学流程编排

这些属于 workflow：

- 章节何时 research
- 章节何时写作
- 何时插入练习
- 何时回写 profile

建议落点：

- `workflows/*`

---

## 7.4 当前最需要修正的边界

### 边界 1：memory 的 canonical 位置

推荐明确：

- canonical：`app.shared.infra.memory`
- `app.teaching.memory`：仅保留兼容 facade，不再新增底层逻辑

原因：

- memory 是系统级能力，不是教学专属能力
- 它涉及路径、存储、读写、一致性，必须只有一个真相源

代码事实：

- `teaching/context.py` 当前就是直接读取 `app.shared.infra.memory`
- 这说明 teaching 已经在做“教学场景适配”，而不是自己实现 memory runtime

### 边界 2：教学函数与 Skill 的关系

建议这样理解：

- `BaseSkill`：通用组合能力，强调接口和策略可复用
- `teaching function`：教学语义动作，强调任务适配和产品表达

当一个教学动作开始依赖：

- 多步检索
- 富媒体生成
- 多轮压缩
- 独立 tracing

就应升级成 `shared/infra/skills` 中的组合 Skill，由 `teaching` 作为调用方或包装方。

### 边界 3：教学文档表达的唯一入口

章节导读、术语速览、学习目标对照、错因块、复习块，建议统一从：

- `app.teaching.documents`

向外提供。  
不要把这些字符串模板再次写回 workflow 节点里。

代码事实：

- `shared/infra/skills/writer.py` 已经调用 `app.teaching.documents.ensure_chapter_learning_scaffold`
- `workflows/digest/docgen/publish.py` 已经调用 `app.teaching.documents.build_document_overview`

这正好说明 teaching 更适合承载“任务适配后的教学表达”。

但边界上还要额外强调：

- 当前若存在 `infra -> teaching`，只能是显式列出的教学表达 hook
- 目标态仍应坚持 `teaching -> infra` 为主依赖方向

---

## 7.5 推荐的教学能力目录

### 7.5.1 `teaching/documents`

负责：

- 文档总览页
- 章节导读
- 学习目标对照
- glossary
- recap / 本章要点
- 课程模式专属块

### 7.5.2 `teaching/diagnostics`（建议新增）

负责：

- 错因解释
- 误区归因
- 学习建议
- 弱点到练习建议的翻译

### 7.5.3 `teaching/practice`（建议新增）

负责：

- 例题讲评模板
- 变式题说明
- 题型拆解模板
- 考试型课程的冲刺建议

### 7.5.4 `teaching/context`

继续负责：

- 教学上下文拼装
- learner profile / recall / knowledge snippets 到教学 prompt 的整合

---

## 7.6 推荐建设的 Teaching Tools

### 面向 `sprint`

- `diagnose_exam_traps`
- `generate_variant_problems`
- `explain_solution_path`
- `build_formula_flashcard`
- `build_last_minute_recap`

### 面向 `systematic`

- `explain_concept_chain`
- `compare_similar_concepts`
- `expand_theorem_intuition`
- `build_prerequisite_bridge`
- `suggest_next_study_path`

### 两种模式都可复用

- `explain_formula`
- `summarize_chapter`
- `translate_profile_signal_to_teaching_advice`

---

## 7.7 外部教育工具怎么接

### 原则

外部 API 的接入点在 `infra`，教学包装在 `teaching`。

### 示例

| 能力 | 底层落点 | 教学落点 |
| --- | --- | --- |
| Wolfram Alpha | `shared/infra/tools` 或 `shared/infra/skills` | `teaching` 调用后组织成“公式解释 / 验证结果” |
| Mathpix | `shared/infra/tools` | `teaching` 用于公式讲解、作业解析 |
| Desmos / GeoGebra | `shared/infra/skills` | `teaching` 决定何时需要交互图 |
| 文生图模型 | `shared/infra/skills/image_generator.py` | `teaching` 决定图像在课程中的教学用途 |
| 动画生成（后续） | `shared/infra/skills` | `teaching` 决定哪些章节值得做动画说明 |

---

## 7.8 LangSmith 元数据建议

教学能力新增 tracing 时，至少要带这些字段：

- `subject`
- `workflow`
- `scene`
- `digest_mode`
- `chapter_index`
- `teaching_action`
- `planner_session_id`
- `confirmed_plan_id`

其中：

- `scene` 例如 `digest_doc` / `interact_chat` / `examine_feedback`
- `teaching_action` 用来标识具体教学动作

---

## 7.9 对 Digest 的具体意义

如果 `teaching` 层落稳，Digest 后续就能做到：

- `writer` 只负责把材料写成草稿
- `teaching/documents` 负责把草稿变成更像讲义的教学结构
- `inject_examine` 注入的内容不再只是“题”，而是“题 + 教学反馈接口”
- `profile` 输出的薄弱点可以被翻译成章节中的针对性提醒

这会让知识文档从“研究整理稿”进一步升级为“课程产品”。

---

## 7.10 一句话结论

`infra` 放接口、抽象、策略和统一 runtime，`teaching` 放 AITeachMe 的任务适配和教学表达，这个方向完全正确。  
真正需要防止的是：在 `teaching` 里再复制一份 memory、tool、path、runtime 逻辑。  
Teaching 层应该成为“会教”的地方，而不是“第二个基础设施层”。
