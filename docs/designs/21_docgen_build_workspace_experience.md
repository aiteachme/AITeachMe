# 21. 知识文档构建工作台体验设计

最后更新：2026-04-21

**状态**：规划中，未实现

本文件补充 `20_docgen_live_build_experience.md`。

`20_docgen_live_build_experience.md` 重点回答：

- DocGen 为什么需要实时过程体验
- 为什么要采用 `SSE + polling fallback`
- 第一批事件和 runtime snapshot 应该长什么样

本文件重点回答：

- AITeachMe 的知识文档构建体验，产品形态上到底应该做成什么
- Planner 和 DocGen 在用户侧应该怎么衔接
- Gemini / Claude 这类产品的过程展示哪些值得借，哪些不适合直接照搬
- 前端页面、信息架构、展示层级和用户可见内容如何设计

---

## 1. 核心判断

AITeachMe 后续要做的，不是“更高级的等待页”，而是一个真正的：

> **知识文档施工现场（Build Workspace）**

用户确认方案后，不应该只看到：

- 进度条
- 空白 loading
- “请稍后刷新”

而应该持续看到：

- 这轮文档准备怎么教
- 系统已经理解了哪些资料
- 章节结构是否成形
- 哪些章节已经开始写
- 每章已经长到了什么程度
- 哪些问题正在复核
- 最终结果如何汇总成一份可继续阅读的知识文档

一句话：

> **用户等待的不是一个后台任务完成，而是一份学习资产逐步长出来。**

---

## 2. 为什么这件事很重要

AITeachMe 的产品定位不是通用聊天助手，而是“赛博私教”和“第二大脑”。

如果知识文档构建阶段只给用户一个进度条，会直接削弱这两个核心感受：

1. **可信感**
   用户看不到系统到底是否真的理解了资料，只能被动等待结果。
2. **陪伴感**
   学习产品最怕“丢下用户自己等”。等待期如果没有内容，用户会更容易退出。
3. **教学感**
   如果中间状态完全不可见，用户感受到的只是“AI 帮我生成了一份文档”，而不是“AI 在为我备课、讲课、整理知识”。
4. **连续性**
   如果过程和结果完全断裂，用户会把 Planner、DocGen、Knowledge Docs 看成三个彼此割裂的功能，而不是一条完整学习链路。

因此，这不是 UI polish，而是产品主链路设计。

---

## 3. 外部产品参考

本节只总结对 AITeachMe 有价值的产品观察，不追求完整竞品分析。

参考资料整理时间：**2026-04-21**

### 3.1 Gemini Deep Research 的可借点

Google 官方资料里，Deep Research 最值得借的不是“能查很多网页”，而是三件事：

1. **先给研究计划，再开始长任务**
   用户先看到 multi-step research plan，可以修改后再启动。
2. **研究过程中用户能理解系统在推进什么**
   Google 在 2025-03 的产品更新里明确提到：Gemini 会在浏览网页时展示 thoughts，让用户能实时理解其研究推进方式。
3. **结果沉淀在 Canvas 中，而不是只停留在对话气泡**
   研究完成后，结果可以在 Canvas 里继续查看、可视化、导出、分享。

对 AITeachMe 的启发：

- Planner 阶段应继续承担“先确认计划”的职责。
- DocGen 阶段也必须有“结果面板”，不能只在聊天区里滚状态。
- 长任务结果应该沉淀到一个可继续编辑/阅读/导出的区域。

### 3.2 Gemini Canvas 的可借点

Gemini Canvas 的价值在于：它把“对话”和“成果物”分成了两个明确区域。

Google 官方帮助文档里可以看到几个关键能力：

- 右侧有独立 Canvas 面板
- 文档可直接编辑
- 变更自动保存
- 支持查看前后版本
- 支持从已有文档继续生成新的衍生内容
- 支持导出到 Docs / Slides

对 AITeachMe 的启发：

- 构建中的知识文档也应该有一个独立成果区，而不是把所有信息都塞进 feed。
- 用户看到的“中间产物”应该越来越接近最终文档本身。
- 后续 Examine / Interact / Profile 都应复用这份文档工作台，而不是另起一个完全独立的页面。

### 3.3 Claude Research 的可借点

Anthropic 官方帮助文档对 Research 的描述有两个很重要的信号：

1. **Research 是 agentic 的多轮搜索与分析**
   它不是一次搜索，而是会根据新发现继续决定下一步要查什么。
2. **结果必须带可验证 citation**
   官方文档多次强调 citations 和 easy-to-check sources。

对 AITeachMe 的启发：

- DocGen 的“过程可视化”不能只展示写作，还要展示它是基于什么来源和证据在推进。
- 但对用户来说，最值得看的不是底层 query log，而是“这章主要参考了哪些资料 / 站点 / 概念证据”。
- 引用和来源透明，是“学习资产可信”而不是“聊天回答可信”的关键。

### 3.4 Claude Artifacts / Interactive Connectors 的可借点

Anthropic 官方关于 Artifacts 和 interactive connectors 的描述说明：

- 复杂任务需要独立的成果空间
- 这个空间可以是 inline card，也可以是 fullscreen
- 用户不需要离开当前对话，就能查看或交互

对 AITeachMe 的启发：

- Build Workspace 最终应该是一个独立的成果工作台
- 但在 Planner 确认页里，也可以先展示一个小型的 inline build card 作为过渡
- 复杂阶段进入全页工作台，简单阶段用卡片提示即可

### 3.5 不应该直接照搬的地方

Gemini / Claude 的很多优秀体验不能直接照抄，原因是 AITeachMe 的目标不同。

不建议直接照搬：

1. **通用 chat-first 结构**
   AITeachMe 是学习产品，不该让构建过程永远从属于聊天流。
2. **原始搜索/推理日志暴露过多**
   学生关心的是“学到了什么”，不是系统发起了第几次 query。
3. **token 级全文流式写作展示**
   对知识文档这种多章并行构建而言，token streaming 可读性很差，也很难解释。
4. **过度强调模型在“思考”**
   学习产品比起“模型很聪明”，更应该强调“知识正在成形，结构正在变清楚”。  

---

## 4. AITeachMe 的产品原则

### 4.1 必须始终展示“内容”，不能只展示“状态”

等待期每一个阶段都应该尽量给用户看到某种中间教学产物：

- 文件理解卡片
- 章节结构
- 草稿片段
- 章节摘要
- 引用来源
- 复核提醒

状态和内容的关系应该是：

```text
状态告诉用户“系统在做什么”
内容告诉用户“已经做出了什么”
```

### 4.2 先确认教学合同，再启动后台长任务

Planner 的职责已经很清楚：

- 读资料边界
- 理解目标
- 生成可确认的章节方案

这个阶段不应该弱化，反而应该明确成为 DocGen 的前置步骤。

对用户的口径也要统一：

```text
先确认怎么学
再开始真正写知识文档
```

### 4.3 对用户展示“教学产物”，而不是“底层执行日志”

DocGen 内部可以有：

- retrieval queries
- claim ledger
- evidence ledger
- conflict report
- repair trace

但用户层应该优先看到：

- 本章讲什么
- 为什么这么分章
- 这章已经写了哪些重点
- 主要参考了哪些来源
- 哪些地方正在复核

### 4.4 最终结果和等待过程必须是同一个工作台

不要做成：

```text
等待页 = 一次性页面
文档页 = 另一个完全不同的页面
```

更合适的方式是：

```text
Build Workspace
  -> 构建中显示中间产物
  -> 构建完成后自然切换成最终文档阅读态
```

也就是说：

> **等待过程是最终文档工作台的“生成阶段”，不是另一种页面。**

### 4.5 可恢复、可回看、可解释，比“很实时”更重要

第一阶段最重要的不是毫秒级实时，而是：

- 页面刷新能恢复
- 用户返回能继续看
- 中间成果不会突然消失
- 结果能解释来源

### 4.6 陪伴层必须轻，不进入后端真相链路

tips / did-you-know / 名人名言 的价值是陪伴，不是业务真相。

所以它们应该：

- 前端静态
- 可暂停
- 不依赖后端
- 不进入 `build_preview`

---

## 5. 推荐产品结构

### 5.1 推荐采用“两幕式体验”

AITeachMe 的知识文档主链路应明确分成两幕。

#### 第一幕：Planner 幕

页面目标：

- 理解你的学习目标和资料范围
- 给出一份可调整、可确认的构建方案

用户看到：

- 思考中的 brief
- 章节大纲
- 方案摘要
- 方案确认按钮

#### 第二幕：DocGen 幕

页面目标：

- 让用户持续看到知识文档是如何从 confirmed plan 长出来的

用户看到：

- 主阶段轨道
- 文件理解
- 文档骨架
- 章节草稿
- 复核状态
- 合并与发布

---

## 6. 页面主路径建议

### 6.1 推荐主路径：KnowledgeDocsPage 成为唯一构建工作台

推荐口径：

- `BuildPlanPage` 只负责 Planner 和 handoff
- `KnowledgeDocsPage` 负责构建中和构建后的统一体验

原因：

1. 当前 `KnowledgeDocsPage` 已经天然承载“最终知识文档”。
2. 如果 `BuildPlanPage` 和 `KnowledgeDocsPage` 都做完整版构建视图，会形成双入口、双状态、双维护。
3. Gemini / Claude 的方向都更接近“一个持续存在的成果空间”，而不是“一个页面等，另一个页面看结果”。

因此推荐：

- 用户在 Planner 中点击“确认并开始构建”
- 构建受理成功后，快速跳转到知识文档工作台
- 在工作台中先看到 Build Workspace
- 文档准备好后，工作台自然切换为阅读态

### 6.2 BuildPlanPage 仍然保留轻量过渡卡片

虽然推荐 KnowledgeDocsPage 作为唯一工作台，但 `BuildPlanPage` 不应该完全黑箱 handoff。

它仍然可以保留：

- 构建请求已受理提示
- 当前构建摘要 bubble
- “进入构建现场”按钮

但不建议继续在 `BuildPlanPage` 上维护一套完整 Build Theater。

---

## 7. 推荐的信息架构

### 7.1 桌面端：三栏工作台

桌面端推荐使用三栏结构。

#### 左栏：阶段轨道 `Build Stage Rail`

只展示用户级阶段，不直接暴露所有 LangGraph 节点。

建议阶段：

1. 冻结方案
2. 理解资料
3. 构建知识骨架
4. 并行写章节
5. 复核与回流
6. 合并与发布

左栏职责：

- 当前阶段定位
- 已完成 / 进行中 / 待开始
- 当前阶段简短解释

#### 中栏：成果画布 `Artifact Canvas`

中栏是主舞台，也是最重要的区域。

设计要求：

- 永远优先展示“当前已经可读的内容”
- 每个阶段切换时，画布展示的对象随之变化
- 画布里的内容尽量越来越接近最终知识文档本体

#### 右栏：动态与来源 `Live Feed + Sources`

右栏分两块：

- 上半：实时动态 feed
- 下半：来源与章节状态

注意：

- feed 和 sources 必须分开
- 不能再把所有事件统一叫“检索来源”

### 7.2 移动端：双抽屉或双 Tab

移动端不建议强行压三栏。

推荐：

- 主区域保留成果画布
- 顶部保留阶段进度
- 右侧信息拆成两个抽屉或两个 tab：
  - `进度`
  - `来源`

移动端优先级应是：

1. 当前阶段
2. 当前中间成果
3. 最近进展
4. 来源明细

---

## 8. 阶段与工作流节点映射

对用户展示时，不应该暴露所有内部 node 名。

推荐映射如下：

### 阶段 1：冻结方案

对应内部：

- build accepted
- planner confirmed

对应节点/状态来源：

- `confirmed_plan`
- `load_context`

用户看到：

- 本次学习目标
- digest mode
- 章节总数
- 选中的资料数
- 方案摘要

### 阶段 2：理解资料

对应内部：

- `prepare_parallel_inputs`
- `enhance_plan_outline`
- `infer_docgen_intent`
- `summarize_files`

用户看到：

- 文件理解卡片
- 每份资料的摘要/标签
- 初步章节目标
- 当前采用的资料策略：本地优先 / 联网优先

### 阶段 3：构建知识骨架

对应内部：

- `confirm_and_dispatch`
- `build_document_backbone`

用户看到：

- 最终章节序列
- 章节之间的依赖关系
- 核心术语/概念组
- 文档骨架摘要

### 阶段 4：并行写章节

对应内部：

- `generate_chapters`
- `enhance_chapters`

用户看到：

- 章节卡片矩阵
- 哪些章节正在写
- 每章已有多少字、多少来源
- 小标题与草稿片段
- 当前章节的引用来源数

### 阶段 5：复核与回流

对应内部：

- `review_chapter`
- `document_consistency_review`
- `repair_or_route`

用户看到：

- 本章已通过 / 复核中 / 待修补
- 整体一致性检查摘要
- 风险提示或 warning 摘要

注意：

- 不直接暴露 claim ledger / repair trace 原始结构
- 只展示对用户可理解的 review 结果

### 阶段 6：合并与发布

对应内部：

- `merge_review`
- `finalize_titles`
- `publish_document`
- 可选的 `graph_ready`

用户看到：

- 最终目录
- 文档合并预览
- 封面与摘要
- 已发布提示

---

## 9. 每个阶段必须展示什么

### 9.1 时间保证

后续实现时，建议把下面这组要求当成体验硬约束。

#### 2 秒内

至少展示：

- 构建已受理
- 方案摘要
- 章节数
- 文件数

#### 10 秒内

至少展示：

- 一份文件理解结果
  或
- 一份章节大纲快照

#### 30 秒内

至少展示：

- 一个章节卡片
  或
- 一段真实草稿片段

#### 每 10-15 秒

至少满足其一：

- 出现一条新的有效事件
- 更新一个章节状态
- 更新一个草稿快照
- 发出一个带解释的 heartbeat

### 9.2 空态原则

允许短暂 skeleton，但不允许长时间完全空白。

如果当前还没有任何中间产物，页面至少要展示：

- 当前阶段说明
- 下一步预计会产出的内容类型
- 已纳入的文件/方案信息

---

## 10. 中间成果应该长什么样

### 10.1 文件理解卡片

每张卡片至少包含：

- 文件名
- 资料类型
- 摘要一句话
- 主题标签
- 当前状态

### 10.2 大纲面板

应展示：

- 章节顺序
- 章节目标
- 预期学习路径

不要只给标题列表，至少要有 objective。

### 10.3 章节卡片板

每张章节卡片建议包含：

- 章节名
- 当前状态
- 当前小标题
- 字数
- 引用来源数
- 草稿摘录

### 10.4 动态 feed

适合展示：

- 状态推进
- 章节开始/完成
- 大纲更新
- 合并完成
- 发布完成

不适合展示：

- 原始 query 文本
- 调用模型名
- 内部 reducer 细节
- 复杂 repair trace

### 10.5 来源面板

来源面板应该与 feed 分开。

来源面板更适合展示：

- 本章主要来源
- 来源标题
- 站点 domain
- 本地文件 / 外部网页区分
- 来源数量

---

## 11. 视觉与交互方向

### 11.1 总体气质

AITeachMe 的 Build Workspace 更适合：

- 研究桌面
- 备课台
- 文档工作区

不适合：

- 纯聊天气泡主导
- 游戏化 loading
- 炫技型模型思考动画

### 11.2 动画原则

动画只服务于两件事：

1. 告诉用户“系统还活着”
2. 帮助用户识别“哪里更新了”

推荐使用：

- 当前阶段轻脉冲
- 新事件淡入
- 新章节卡片上浮
- 新草稿片段高亮

不建议：

- 整页持续强闪动
- 大量无意义骨架 shimmer
- 把模型“思考”拟人化成很重的戏剧化动画

### 11.3 字体与风格方向

核心内容区应更接近文档阅读，不要太 chat UI。

建议：

- 标题与摘要用更有文档感的字体层次
- 草稿区采用“接近最终文档”的样式
- 让用户感觉自己已经进入文档，而不是还停留在 loading 页

---

## 12. 当前代码的关键观察

### 12.1 Planner 的过程体验已经证明这条路是可行的

当前 Planner 已经具备：

- `token` 流式文本
- `status` 阶段事件
- 结构化 stream event
- 前端可见的思考过程与大纲预览

参考：

- `backend/app/api/knowledge_docs.py::_planner_stream_response`
- `backend/app/workflows/digest/planner/README.md`
- `frontend/src/pages/BuildPlanPage.tsx`

这说明：

> “边生成边让用户看到结构化过程” 在你们当前架构里已经被证明可行。

### 12.2 DocGen 已经有数据基础，但还没有被组织成真正的工作台

当前后端已写入：

- `current_stage_description`
- `chapter_progress`
- `recent_events`
- `latest_chapter_titles`
- `draft_excerpt`

参考：

- `backend/app/utils/docgen_store.py`
- `backend/app/workflows/digest/docgen/lib/build_lifecycle.py`
- `backend/app/schemas/knowledge.py`

当前前端也已有：

- `BuildView`
- `BuildProcessTimeline`
- `BuildMaterialPipeline`
- `BuildChapterProgress`
- `BuildResearchSources`
- `DocumentCanvas`

但问题在于：

- 这些数据和组件还没有形成“一个统一的工作台体验”
- feed 与 sources 语义混杂
- 大量中间产物还没被单独建模

### 12.3 当前有一条隐藏的错误方向：双工作台

当前 `BuildPlanPage` 与 `KnowledgeDocsPage` 都有构建态相关展示代码。

这会天然引出一个问题：

```text
到底哪个页面才是用户真正要看的构建现场？
```

如果两个页面都做完整版 Build Workspace，会造成：

- 状态同步复杂
- 入口重复
- 维护重复
- 用户心智混乱

所以推荐明确收敛：

> **KnowledgeDocsPage 才是唯一的 Build Workspace。**

### 12.4 当前最明显的语义错位点

`BuildResearchSources` 现在把 `recent_events` 统一展示成“检索来源”。

但实际上 `recent_events` 已经混合了：

- 研究事件
- 章节生成事件
- 复核事件
- 发布事件

这意味着后续必须拆成：

- `BuildLiveFeed`
- `BuildSourcePanel`

---

## 13. 推荐组件结构

后续前端建议收敛到下面这组组件：

```text
KnowledgeBuildWorkspace
  BuildWorkspaceHeader
  BuildStageRail
  BuildArtifactCanvas
    BuildPlanSnapshot
    BuildFileInsights
    BuildOutlineSnapshot
    BuildBackboneSnapshot
    BuildChapterBoard
    BuildReviewSnapshot
    BuildMergedPreview
  BuildLiveFeed
  BuildSourcePanel
  BuildDidYouKnow
```

说明：

- `BuildView` 可以作为过渡壳，但长期建议演进成 `KnowledgeBuildWorkspace`
- `DocumentCanvas` 的职责建议进一步聚焦为“成果画布”
- `BuildResearchSources` 长期应拆分重命名

---

## 14. 后续实施优先级

### Phase A：统一产品主路径

目标：

- 确定 `KnowledgeDocsPage` 为唯一 Build Workspace
- `BuildPlanPage` 只保留 handoff 与轻量过渡卡片

这是最重要的产品决策，优先级高于炫技 UI。

### Phase B：把当前 polling 数据组织成真正的工作台

目标：

- 不引入 SSE 也能先让页面“有内容”
- 拆开 `feed` 与 `source`
- 新增 outline / backbone / chapter board / merged preview

### Phase C：接入 DocGen SSE

目标：

- 用 `SSE + polling fallback` 驱动工作台
- 让 feed、章节状态和预览做到持续更新

### Phase D：让工作台成为最终文档页的生成阶段

目标：

- 构建完成时自然切换到阅读态
- 保留已构建出的目录、版本、来源和摘要
- 为 Interact / Examine / Profile 留出复用入口

---

## 15. 一句话结论

AITeachMe 的 DocGen 后续改进方向，不应该理解为：

```text
给知识文档页加一个更好看的 loading
```

而应该理解为：

```text
把知识文档生成过程做成一个可恢复、可解释、可持续观看、最终自然长成正式文档的 Build Workspace
```

更具体一点：

> **Planner 负责让用户确认“怎么学”，DocGen 负责让用户看见“知识文档怎么长出来”。**

---

## 16. 参考资料

以下是本设计稿整理时重点参考的官方公开资料：

- Google Gemini Apps Help: Deep Research  
  `https://support.google.com/gemini/answer/15719111?hl=en`
- Google Gemini Apps Help: Canvas  
  `https://support.google.com/gemini/answer/16047321?hl=en`
- Google Blog: Gemini Deep Research announcement  
  `https://blog.google/products-and-platforms/products/gemini/google-gemini-deep-research/`
- Google Blog: Gemini app updates, March 2025  
  `https://blog.google/products-and-platforms/products/gemini/new-gemini-app-features-march-2025/`
- Anthropic Help: Using Research on Claude  
  `https://support.claude.com/en/articles/11088861-using-research-on-claude`
- Anthropic Help: Enabling and using web search  
  `https://support.claude.com/en/articles/10684626-enabling-and-using-web-search`
- Anthropic Blog: Artifacts  
  `https://claude.com/blog/artifacts`
- Anthropic Help: interactive connectors / remote MCP  
  `https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp`
