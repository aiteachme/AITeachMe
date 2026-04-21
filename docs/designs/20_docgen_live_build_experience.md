# 20. DocGen 过程可视化与 Build Workspace 方案

最后更新：2026-04-21

状态：规划中，面向当前实现收敛

---

## 1. 这份文档解决什么问题

DocGen 现在已经不是“完全没有过程数据”的状态了。

当前代码里，后端已经持续写入：

- `current_stage_description`
- `chapter_progress`
- `recent_events`
- `latest_chapter_titles`
- `draft_excerpt`

对应位置：

- `backend/app/utils/docgen_store.py`
- `backend/app/workflows/digest/docgen/lib/build_lifecycle.py`
- `backend/app/schemas/knowledge.py`

前端也已经有初版等待态组件：

- `frontend/src/components/knowledge-docs/BuildView.tsx`
- `BuildProcessTimeline.tsx`
- `BuildChapterProgress.tsx`
- `BuildResearchSources.tsx`

所以这次不是从零设计一套“理想中的实时构建系统”，而是把现有能力收拢成一个更清晰的产品形态：

> 让用户在知识文档生成期间，始终看到正在长出来的学习内容，而不是只看到一个百分比。

---

## 2. 核心判断

### 2.1 `KnowledgeDocsPage` 应该是唯一的 Build Workspace

`BuildPlanPage` 负责确认“怎么学”。

`KnowledgeDocsPage` 负责展示“知识文档怎么长出来”。

不应该让两个页面都承载完整的 DocGen 过程可视化，否则会出现：

- 两套构建态 UI
- 两套状态同步
- 两个“真正工作台”的入口
- 用户心智混乱

统一口径：

```text
Planner 负责确认方案。
DocGen 工作台负责展示构建过程和最终文档。
```

### 2.2 过程可视化展示的是“教学产物”，不是底层日志

对用户最有价值的，不是：

- 第几次 query
- 哪个模型名
- 哪个 reducer merge 了什么

而是：

- 本轮文档准备怎么组织
- 已经理解了哪些资料
- 章节结构有没有成形
- 哪些章节正在写
- 现在能看到什么草稿
- 哪些地方在复核

### 2.3 不做 token streaming，做 artifact-first streaming

DocGen 是多章并行 fan-out。

如果直接做 raw token streaming，会出现：

- 并行章节输出难以解释
- 前端很难稳定排版
- 用户看到很多“字在动”，但不清楚知识文档到底长成了什么

正确方向是：

> 优先流式展示“可读的中间产物快照”，而不是“原始 token”。

### 2.4 SSE 是实时层，polling 是恢复层

这两者不是替代关系，而是分工关系：

- SSE：负责实时反馈、动态感、过程陪伴
- polling：负责首屏恢复、断线兜底、刷新重建

---

## 3. 用户态阶段模型

前端不应该直接暴露所有 LangGraph 节点名，而应该收口为 6 个用户能理解的大阶段。

| 用户阶段 | 对应后端阶段 / 节点 | 用户应该理解成什么 |
| --- | --- | --- |
| 冻结方案 | `build_accepted`、`planner_confirmed`、`load_context` | 方案已经锁定，系统开始按章执行 |
| 理解资料 | `preparing_docgen_context`、`prepare_parallel_inputs` | 正在读材料、判断重点、明确写法 |
| 构建骨架 | `dispatch_ready`、`building_document_backbone`、`confirm_and_dispatch`、`build_document_backbone` | 正在搭整本文档的概念骨架与章节执行合同 |
| 并行写作 | `generating_chapters`、`enhancing_chapters`、`generate_chapters`、`enhance_chapters` | 各章节正在研究、成稿、增强 |
| 复核回流 | `reviewing_content`、`content_reviewed`、`repairing_or_routing`、`repair_routed` | 正在检查覆盖、证据和一致性，并做安全修补 |
| 合并发布 | `merge_reviewed`、`titles_finalized`、`publishing`、`completed` | 正在收口整本内容并发布正式文档 |

设计要求：

- 左侧轨道只显示这 6 个阶段。
- 中央画布始终显示与当前阶段最相关的“产物”。
- 右侧实时区显示最近发生了什么，但不能抢主画布。

---

## 4. 页面结构

### 4.1 桌面端推荐结构

推荐采用“头部 + 三栏工作台”。

```text
Build Workspace
  Header
  Left Rail
  Artifact Canvas
  Right Rail
```

具体分工：

#### Header

展示本轮构建的总状态：

- 当前阶段标题
- 当前阶段描述
- 进度百分比
- 构建模式 `systematic / sprint`
- 章数、资料数、实时更新时间

#### Left Rail

只做稳定导航，不承担复杂内容：

- 六阶段轨道
- 已纳入资料卡片列表
- 当前模式说明

#### Artifact Canvas

这是整个页面的核心。

要求：

- 永远优先展示“当前已经可读的内容”
- 展示对象随阶段变化
- 阶段切换时保留上一个稳定产物，避免页面忽然清空

#### Right Rail

拆成两个明确区域：

- `Live Feed`：最近发生了什么
- `Sources`：本轮主要参考了哪些来源

当前 `BuildResearchSources` 把 `recent_events` 全部叫做“检索来源”，语义已经不准确，后续必须拆分。

### 4.2 移动端推荐结构

移动端不要强压三栏。

推荐结构：

- 顶部固定 Header
- 中间保留 `Artifact Canvas`
- 底部或侧边抽屉切换 `进度 / 来源`

移动端优先级：

1. 当前阶段
2. 当前可读产物
3. 最近进展
4. 来源与细节

---

## 5. 每个阶段必须展示什么

### 5.1 冻结方案

最少展示：

- `plan_summary`
- 章节总数
- 已纳入资料数
- 当前模式

推荐展示：

- 章节列表简表
- 本轮是否为 `search-only mode`

### 5.2 理解资料

最少展示：

- 文件理解卡片
- 当前资料策略：`local_first / web_first`
- 写作意图摘要

推荐展示：

- 文件标签
- 哪些文件更偏向哪一章

### 5.3 构建骨架

最少展示：

- 章节顺序
- 每章目标一句话
- 整体学习路径摘要

推荐展示：

- 核心术语或概念树摘要
- 章节依赖关系提示

### 5.4 并行写作

最少展示：

- 章节卡片板
- 当前正在写的章节高亮
- 至少一个章节的草稿片段

推荐展示：

- 字数
- 来源数
- 当前小标题
- 是否使用 fallback

### 5.5 复核回流

最少展示：

- 哪些章节已复核完成
- 是否存在 warning
- 当前整本一致性检查状态

推荐展示：

- 风险摘要卡
- “本轮正在修什么” 的用户友好说明

### 5.6 合并发布

最少展示：

- 最新目录
- 合并后的文档片段
- 发布完成提示

推荐展示：

- 章节最终标题列表
- 封面预告
- 发布时间

---

## 6. Artifact Canvas 规则

中央画布必须遵守以下规则：

### 6.1 同一时刻只突出一个主产物

每个阶段只突出一个主要对象：

- 冻结方案：方案快照
- 理解资料：文件理解卡片
- 构建骨架：大纲 / 骨架快照
- 并行写作：章节卡片板 + 当前草稿
- 复核回流：复核摘要
- 合并发布：整本预览

### 6.2 阶段切换时保留上一个稳定产物

例如从“构建骨架”进入“并行写作”时：

- 大纲不要立刻消失
- 应退到次级区域
- 新出现的章节卡片成为主产物

这样用户不会觉得页面重新开始了一轮空白等待。

### 6.3 所有动态都必须落到“内容变化”

允许动画，但动画只能服务于内容理解：

- 当前章节高亮
- 新草稿卡淡入
- feed 新事件滑入
- 进度条缓动

不建议：

- 多区域同时强动画
- 持续闪烁的装饰性效果
- 只动不产出内容

---

## 7. “始终有内容可看”的硬约束

这是这套体验最重要的约束。

### 7.1 时间保证

#### 2 秒内

必须看到：

- 构建已受理
- 方案摘要
- 章节数
- 文件数

#### 10 秒内

至少出现以下之一：

- 一张文件理解卡
- 一份大纲快照
- 一条明确的“当前正在产出什么”的阶段说明

#### 30 秒内

至少出现以下之一：

- 一个章节卡片
- 一段真实草稿片段
- 一条解释性很强的回执，说明为什么此时还没有章节预览

#### 每 10-15 秒

至少发生以下之一：

- 新事件进入 feed
- 某章状态变化
- 草稿片段更新
- 心跳事件解释当前卡在哪一步

### 7.2 空态原则

允许短暂 skeleton，但不允许长时间完全空白。

如果还没有任何中间产物，页面也至少要保留：

- 当前阶段
- 本轮方案摘要
- 已纳入资料
- 下一步预计会出现什么产物

### 7.3 断线原则

如果 SSE 断开：

- 保留最后一个稳定产物
- 明确提示“实时连接已断开，正在改用刷新同步”
- polling 继续工作

---

## 8. 当前实现对应关系与主要缺口

### 8.1 已经具备的基础

当前实现已经具备这些能力：

- `build_preview` 可以驱动章节列表和动态 feed
- `build_status` 可以驱动阶段轨道和进度
- `publish_docgen_progress(...)` 已经预留结构化事件出口
- `BuildView` 已经是 Build Workspace 的雏形

### 8.2 当前最明显的缺口

#### 缺口一：预览对象还不够“面向工作台”

当前 `KnowledgeBuildPreviewResponse` 里有：

- `plan_summary`
- `chapter_progress`
- `recent_events`
- `latest_chapter_titles`
- `draft_excerpt`

但还缺少更明确的中间产物：

- `outline_snapshot`
- `chapter_previews`
- `merge_preview`

#### 缺口二：`recent_events` 的语义混杂

当前它同时承载：

- 检索事件
- 写作事件
- 复核事件
- 发布事件

前端不能继续把这整块内容都叫做“检索来源”。

#### 缺口三：部分前端状态判断仍带旧语义

当前前端某些地方还把章节活跃状态理解为：

- `researching`
- `drafting`

但后端真实写入的状态已经是：

- `generating`
- `enhancing`
- `reviewing`
- `reviewed`
- `completed`

这类语义错位会直接影响用户看到的构建态判断。

#### 缺口四：现有设计稿分裂成三份，边界重复

之前的 `20 / 20b / 21` 分别讲产品、协议、工作台，但重复度很高。

本轮收敛后的原则是：

- `20` 只讲产品形态和展示规则
- `21` 只讲 SSE 协议和落地顺序

---

## 9. 视觉与样式原则

DocGen 工作台的气质应该更像“备课台 + 成果画布”，而不是聊天窗口。

推荐风格：

- 主背景偏纸面和石色系，减少大面积纯蓝
- 状态强调色用天空蓝，完成态用绿色
- 主画布可保留更强的文档感和 serif 字体
- 指标和状态区维持简洁 sans-serif

动效原则：

- 一次只让一个主对象动起来
- 用淡入、缓动、骨架切换，不用夸张弹跳
- 进度只是辅助，不是视觉主角

---

## 10. 推荐实施顺序

### Phase A：先把现有 polling 版工作台收口

目标：

- 统一 `KnowledgeDocsPage` 为唯一 Build Workspace
- 拆开 `Live Feed` 和 `Sources`
- 修正章节状态语义
- 让中央画布真正按阶段切换产物

### Phase B：补上 DocGen SSE

目标：

- 用 SSE 驱动 feed、阶段和章节实时变化
- 继续保留 polling 兜底

### Phase C：补齐可恢复中间产物

目标：

- 增加 `outline_snapshot`
- 增加 `chapter_previews`
- 增加 `merge_preview`
- 支持刷新后恢复到接近断开前的工作台状态

---

## 11. 一句话结论

这次改造的正确方向不是“把等待页做得更花”，而是：

> 把知识文档生成过程做成一个用户愿意停留、始终看得到内容、最后自然长成正式文档的 Build Workspace。
