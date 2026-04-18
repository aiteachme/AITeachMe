# 22. Planner V4 研究面板与大纲生成改造计划

> 最后更新：2026-04-16
> 适用范围：`backend/app/workflows/digest/planner/` 与 `frontend/src/pages/BuildPlanPage.tsx`
> 状态说明：本文是历史探索方案。当前 Planner 已收敛为
> `digest/planner/README.md` 中的轻量四步链路，不在 Planner 阶段做本地
> RAG 或外部 Web 检索；检索与证据增强由 DocGen 负责。

## 一句话结论

当前 Planner V3.2 的主流程方向是对的，但还没有真正达到“Deep Research 风格首屏”的产品质感。

当前最明显的差距不是节点顺序，而是这 4 件事：

1. 草稿阶段的定位需要继续保持轻量，不应被做成“先重吃正文”的慢路径。
2. “概念增强”还不是模型驱动的选源与开读，更像规则检索补锚点。
3. 前端更适合先把 SSE 事件展示清楚，而不是马上扩成复杂研究面板。
4. V3.2 新链路和旧 `load_context / ground_concepts / draft_plan` 旧链路仍并存，后续很容易继续漂移。

因此本轮建议不是大改总图，而是在现有 V3.2 上继续收敛成一个更明确的 V4：

```text
prepare_material_context
  -> bootstrap_research_surface
       ├─ stream_plan_sketch(reason, SSE)
       └─ extract_learning_intent(primary, structured)
  -> enhance_concepts
       ├─ retrieve local/web candidates
       ├─ select what to open with primary model
       └─ read chosen sections/pages into grounding pack
  -> compose_plan_outline(reason, structured)
  -> finalize_plan_contract
```

## 1. 这次评估的核心判断

### 1.1 你现在想的流程是合理的

你提出的流程：

1. 草稿生成：`reason` 模型，SSE 输出可视草稿
2. 意图识别：并行抽取用户目标、约束和检索输入
3. 概念增强：先检索，再决定具体打开哪些内容读
4. 综合生成：把草稿、增强结果、提示词、上下文合成为计划大纲

这套思路和当前主流 Deep Research 产品非常接近，尤其有两个点是对的：

- **先给用户一个“可看的研究面板”**，而不是一上来闷头跑完才吐结果。
- **把“检索候选”和“真正打开阅读的上下文”分开**，避免把几十个来源一次性塞进大模型。

### 1.2 但当前实现还没有完全落到这层

V3.2 已经实现了：

- `prepare_material_context`
- `generate_plan_preview` 内部并行：
  - `stream_plan_sketch`
  - `extract_learning_intent`
- `probe_supporting_evidence`
- `compose_plan_contract`
- `finalize_plan_contract`

也就是说，图结构已经接近目标流；真正缺的是：

- 概念增强阶段的模型参与度
- 前端对 SSE planning 过程的更清晰展示
- 旧链路的彻底退场

## 2. 外部产品调研结论

以下只记录本轮后续改造真正有参考价值的部分。界面细节中未被官方逐字描述的地方，统一视为**基于官方描述的推断**。

### 2.1 OpenAI Deep Research

参考：

- OpenAI 发布页（2025-02-02，含 2026-02-10 更新）  
  https://openai.com/index/introducing-deep-research/
- OpenAI Help Center FAQ（本次访问时显示最近更新约为 2026-04-14）  
  https://help.openai.com/en/articles/10500283-deep-research-faq

可以确定的产品特征：

1. **开始前有 research plan**
   - OpenAI FAQ 明确写了：用户描述目标后，ChatGPT 会先生成一个 proposed research plan，用户可以 review 和 modify，然后再开始研究。
2. **运行中有 process visibility**
   - 发布页和 FAQ 都提到运行时可跟踪 progress，可以 interrupt 后继续 refine。
3. **结果页是结构化报告，而不是仅聊天泡泡**
   - FAQ 明确提到 fullscreen report view、table of contents、sources used、activity history。

产品含义：

- OpenAI 的“首屏大纲”更像**研究执行计划**，不是最终知识文档目录。
- 目录化报告和 sources/activity history 是**完成后的 review 面板**。

### 2.2 Google Gemini Deep Research

参考：

- Gemini Deep Research 首次发布页（2024-12-11）  
  https://blog.google/products-and-platforms/products/gemini/google-gemini-deep-research/
- Gemini Deep Research 升级页（2025-03-13）  
  https://blog.google/products-and-platforms/products/gemini/new-gemini-app-features-march-2025/

可以确定的产品特征：

1. **开始前是 multi-step research plan**
   - Google 首发页明确写了：用户输入问题后，Deep Research 会创建一个 multi-step research plan，用户可以 revise 或 approve。
2. **研究过程是多轮搜索-阅读-再搜索**
   - Google 明确描述它会像人一样搜索、读到信息、根据新发现继续搜索，重复多轮。
3. **新版开始强调“实时看见思考过程”**
   - 2025-03-13 的更新页明确写了：Gemini now shows its thoughts while it browses the web。

产品含义：

- Google 的首屏重点也是**研究计划 + 运行时过程可见性**。
- 报告目录是结果，不是第一步。

### 2.3 对 AITeachMe 的直接启发

AITeachMe 的 Planner 不是通用研究助手，而是“知识文档构建前的研究与编排面板”。因此它的首屏应该拆成两个层次：

1. **研究面板**
   - 我将如何理解你的目标
   - 我优先查哪些本地材料
   - 哪些地方需要外部校准
   - 当前还缺什么确认

2. **构建大纲草稿**
   - 暂定章节
   - 每章关注点
   - 后续 DocGen 将怎么写

换句话说，首屏不应该只有“一个 markdown 草稿”，而应该是：

- 上层：研究计划与证据路径
- 下层：知识文档大纲草稿

## 3. 当前代码的主要问题

下面只列值得优先处理的重问题。

### 3.1 草稿阶段应继续保持轻量，不要被做成慢路径

当前 `build_plan_sketch_prompt(...)` 主要提供的是：

- 学科/主题
- 用户目标
- 模式、语气
- topic hints
- 文件名
- 最近几轮对话

这套输入对“草稿试水层”来说是合理的，因为它的目标本来就不是重理解正文，而是：

1. **尽快通过 SSE 给前端可见内容。**
2. **先把用户目标、模式和大致方向固定下来。**
3. **把真正重的资料理解放到概念增强和最终合成。**

所以 V4 这里不建议把草稿节点改成重上下文节点；更合理的优化方向是：

- 保持草稿 prompt 轻量
- 让概念增强真正承担“读哪些内容、打开哪些上下文”的工作
- 让最终 compose 节点去吃增强后的 grounding pack

### 3.2 概念增强还不是“先检索，再判断开读哪些内容”

当前 `probe_supporting_evidence` 已经有检索、筛选、打开来源的框架，但还存在两个缺口：

1. **来源筛选仍是 rule-based**
   - `rule_based_source_triage(...)` 只是按结果顺序去重和截断。
2. **本地来源没有真正“开读正文”**
   - 对 local hit 目前主要保留 `snippet / preview`，而不是再抽取一小包高价值 section 作为 grounding context。

这意味着现在的“concept enhancement”更像：

```text
快速检索 -> 挑几个来源 -> 给出摘要
```

而不是你想要的：

```text
快速检索 -> 模型决定该读哪几段 -> 打开这些段 -> 再总结成 grounding pack
```

### 3.3 前端当前最值得做的是把 SSE 事件展示清楚

当前前端已经能：

- 流式展示 markdown 草稿
- 展示少量 runtime timing
- 展示状态文本

但对当前阶段来说，前端不一定需要马上扩成复杂研究面板。

更合适的最小目标是：

- **把现有 SSE 事件展示好**
- 让用户清楚知道当前在做哪一步
- 让草稿 token 流和阶段事件配合起来更顺

这一轮前端优先级应该是：

1. 事件可见
2. 文案清楚
3. 顺序稳定

而不是额外堆太多结构化卡片。

### 3.4 旧 Planner 链路仍留在目录里，增加后续漂移风险

目录下仍同时存在：

- `load_context.py`
- `ground_concepts.py`
- `draft_plan.py`

以及与之绑定的旧 prompt 出口。

这会有两个风险：

1. 新人读代码时，不清楚哪条才是当前真链路。
2. 后面小改需求容易不小心继续补在旧文件上，导致双轨维护。

当前这个问题已经不只是“有点乱”，而是会直接影响后续 Planner 的持续演进速度。

## 4. V4 目标流

### 4.1 目标原则

V4 不追求把 Planner 做成完整 deep research report，而是追求 4 个结果：

1. **首屏更快可见**
2. **证据增强更像真实研究**
3. **前端能把 planning 过程用 SSE 事件讲清楚**
4. **旧链路彻底退场**

### 4.2 建议流程

```text
prepare_material_context
  -> bootstrap_research_surface
       ├─ stream_plan_sketch(reason, SSE markdown)
       └─ extract_learning_intent(primary, structured)
  -> enhance_concepts
       ├─ build retrieval candidates
       ├─ run local-first retrieval
       ├─ use primary model to choose which sections/pages to open
       ├─ read selected local sections and web pages
       └─ produce grounding pack
  -> compose_plan_outline(reason, structured)
  -> finalize_plan_contract
```

### 4.3 每一步建议做什么

#### A. `prepare_material_context`

继续复用现有 `DigestMaterialContext`，但新增一个给 Planner 用的“代表性正文摘录”构建函数，输出：

- `representative_sections`
- `chapter_like_sections`
- `formula_or_question_dense_sections`

目标不是把大段正文喂给模型，而是给草稿和合成节点各准备一小包高信号 context。

#### B. `bootstrap_research_surface`

继续保留并行：

- `stream_plan_sketch`
- `extract_learning_intent`

但需要新增：

- `PlanSurfaceBootstrap` 结构
- 明确区分：
  - `research_tasks`
  - `draft_outline`
  - `clarifications`
  - `source_policy`

这里的 markdown 草稿仍然保留，因为它适合 SSE。
但同时要给前端一份结构化 payload，不能只有 markdown。

#### C. `enhance_concepts`

这是 V4 的核心增量。

建议拆成 3 小步：

1. **候选检索**
   - local sections 优先
   - web 只补 top-k 候选
2. **模型判读**
   - 用 `primary` 模型判断：
     - 哪些 section/page 值得打开
     - 为什么打开
     - 对哪些暂定章节有帮助
3. **开读聚合**
   - local：读取 section 正文
   - web：读取 page 正文摘要
   - 产出 `GroundingPack`

`GroundingPack` 至少包含：

- `selected_queries`
- `selected_sources`
- `opened_contexts`
- `core_concepts`
- `chapter_grounding_hints`
- `gap_notes`

#### D. `compose_plan_outline`

仍使用 `reason` 模型，但输入要从“草稿 + 意图 + 轻证据”升级为：

- markdown 草稿
- structured intent
- representative sections
- opened local contexts
- opened web contexts
- grounding pack
- latest_plan（如果是 revise）

这里输出继续是结构化 `BuildPlannerDraft`。

#### E. `finalize_plan_contract`

继续保留现有 normalize/fallback，但目标改成：

- 只做 contract 收敛
- 不再承担过多“补主题”的职责

换句话说，主题边界应该在前面两步尽量收稳，finalize 只兜底。

## 5. 前端可视化建议

### 5.1 首屏不要只放一个 markdown 卡片

建议拆成四块：

1. **研究计划卡**
   - 目标类型
   - source policy
   - 当前模式
   - 待确认点
2. **草稿大纲卡**
   - markdown 预览
3. **证据面板**
   - 本地命中数
   - 外部命中数
   - 已筛选来源
   - 已打开上下文
4. **运行进度卡**
   - 当前步骤
   - 最近事件
   - step timing

### 5.2 SSE 事件建议升级为 typed planner events

当前 Planner 事件已经有命名，但前端基本把它们折叠成了状态文本。

建议前后端统一成以下 typed payload：

- `planner.material.ready`
- `planner.sketch.delta`
- `planner.intent.ready`
- `planner.sources.triaged`
- `planner.contexts.opened`
- `planner.evidence.ready`
- `planner.plan.composing`
- `planner.plan.ready`

并保证每类事件都包含清晰 payload，而不是只靠 `detail` 字段。

### 5.3 UI 目标不是“更炫”，而是“更可解释”

前端重点不在做复杂动画，而在于让用户知道：

- 系统现在理解了什么
- 读了哪些材料
- 为什么这样分章
- 还有哪些地方不确定

## 6. 代码层改造建议

### Phase 1：不改 API 面，先把 Planner 变扎实

优先做：

1. 保持草稿节点轻量和快速 SSE
2. `probe_supporting_evidence` 升级成“候选检索 + 模型选读 + 开读聚合”
3. `compose_plan_contract` 输入接入 grounding pack
4. 前端优先把 SSE 事件展示清楚，而不是扩很多新面板

这一步应该尽量不改持久化表结构，只扩展 workflow state 和 SSE payload。

### Phase 2：清旧链路

在 V4 跑稳后，处理：

- 退役旧 `load_context / ground_concepts / draft_plan`
- 清理 `prompts/__init__.py` 中旧出口
- 缩减 state 里旧 timing 字段
- 删除旧 generation mode 残留

### Phase 3：是否增加“研究计划先确认”开关

这不是第一优先级，但值得保留为后续选项：

- 默认仍自动继续跑
- 高成本模式下允许用户先确认 research plan 再继续

这样既保留当前流畅性，也能在重资料、重外部研究场景下更像 OpenAI / Gemini。

## 7. 这轮建议的验收标准

V4 最少应满足：

1. 同一批资料下，草稿章节标题明显更贴近正文而不是只贴 topic hints。
2. 本地 section 能进入最终 composer's grounding context，而不只是 snippet。
3. 前端能看到：
   - intent
   - query
   - selected/opened sources
   - evidence summary
4. 目录里只保留一条当前 Planner 主链路，旧链路不再继续扩散。

## 8. 当前建议的实现顺序

建议按这个顺序落：

1. **先补文档与接口心智**
   - 明确 V3.2 和 V4 的边界
2. **再补后端 grounding**
   - 这是大纲质量的真正抓手
3. **再补前端 research surface**
   - 否则后端事件再丰富也看不出来
4. **最后清理旧链路**
   - 避免一边扩新一边背双轨历史包袱

## 9. 开放问题

下面这些点如果后续需要更细，可以再单独拍板：

1. `enhance_concepts` 的“模型选读”是否允许调用外部 source triage prompt，还是先走轻量结构化输出。
2. 本地 section 开读是传整段、压缩摘要，还是抽关键句证据块。
3. revise 模式是否要显式展示“相对上一版的变更 diff”。
4. 首屏是否加入“先确认研究方向再继续”的显式暂停点。

## 10. 一句话收束

Planner 下一步最重要的，不是再多加一个节点名，而是把它真正做成一个：

**先解释研究方向，再展示证据路径，最后产出知识文档大纲的 planning surface。**
