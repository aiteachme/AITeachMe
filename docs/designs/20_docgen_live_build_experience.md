# 20. 知识文档构建实时可视化与 SSE 方案

最后更新：2026-04-21

**状态**：规划中，未实现

---

## 1. 背景

当前知识文档构建页已经有一版等待态，但核心仍然是：

- 后端 `POST /api/v1/subjects/{subject}/knowledge/build` 只负责受理并启动后台任务
- 前端通过 `POST /api/v1/subjects/{subject}/knowledge/docs` 轮询读取 build status / build preview
- 页面主体仍然是“进度条 + 少量预览卡片”

这对短构建还够用，但对真实的长构建不够：

- 用户看不到“系统具体在做什么”
- 用户看不到“已经读了哪些文件、抽出了什么大纲、哪一章已经开始成稿”
- 长时间只有进度条，会让用户误以为卡住，或者直接离开页面

目标不是把等待页做得更花，而是把它升级成一个**可感知、可恢复、可解释**的实时构建体验。

---

## 2. 当前现状

### 2.1 后端现状

当前已有的基础能力：

- Planner 已经有成熟 SSE 实现  
  入口参考：`backend/app/api/knowledge_docs.py::_planner_stream_response`
- DocGen 已经有结构化的 runtime build status / preview / metrics  
  数据来源参考：
  - `backend/app/utils/docgen_store.py`
  - `backend/app/workflows/digest/docgen/lib/build_lifecycle.py::get_docgen_result`
- DocGen 已经会持续写入：
  - `chapter_progress`
  - `recent_events`
  - `latest_chapter_titles`
  - `draft_excerpt`

当前缺口：

- DocGen 没有正式 SSE 入口
- 构建过程的“中间可视化产物”还不够细
- 当前 preview 更像“轮询时顺手带一点信息”，不是“专门为实时体验设计的数据面”

### 2.2 前端现状

当前知识文档等待页已经有：

- `BuildView`
- `BuildProcessTimeline`
- `BuildMaterialPipeline`
- `BuildChapterProgress`
- `BuildResearchSources`
- `DocumentCanvas`

参考：

- `frontend/src/components/knowledge-docs/BuildView.tsx`
- `frontend/src/components/pages/DigestBuildPanel.tsx`
- `frontend/src/components/knowledge-docs/hooks/useDocMarkdown.ts`

当前缺口：

- 还是以 polling 为主，不是真正“推送式”
- 缺少清晰的“文件 -> 大纲 -> 章节草稿 -> 合并发布”可视流程
- 缺少“正在写第几章、这章写到哪了、草稿长什么样”的更强反馈
- 缺少降低等待流失的陪伴内容，例如 tips / did-you-know / 名人名言

---

## 3. 目标与非目标

### 3.1 目标

这次改造要达到 5 个目标：

1. 用户在构建开始后 1-2 秒内就能看到明确反馈，不再只有空进度条。
2. 用户能连续看到构建过程中的关键中间状态：
   - 已纳入资料
   - 资料解析/摘要
   - 章节大纲
   - 章节草稿
   - 合并与发布
3. 主体验改为 SSE 实时流，减少“轮询看起来像卡住”的感觉。
4. 页面刷新或重新进入时，仍能通过当前 build status / preview 恢复大部分上下文。
5. 在等待过程中加入轻量陪伴内容，让用户更愿意留在页面。

### 3.2 非目标

本轮不做：

- 把 DocGen 改成 token 级全文流式输出
- 把每章完整 Markdown 实时无限流给前端
- 把 SSE 替换掉所有现有 polling
- 在第一阶段引入 WebSocket
- 为所有 lane 都做统一流式体验

一句话：

> 第一阶段的目标不是“在线看 AI 打字”，而是“让用户清楚知道构建正在推进，而且推进到了哪里”。

---

## 4. 目标体验

## 4.1 用户看到的等待页

等待页应该从“单条进度条”升级成“构建剧场（Build Theater）”。

推荐布局：

### A. 顶部状态头

- 当前阶段标题
- 进度百分比
- 关键指标
  - 已处理资料数
  - 已生成章节数
  - 当前正在写的章节
  - 最近一次事件时间

### B. 左侧阶段轨道

固定展示主流程：

1. 已接收构建
2. 理解资料
3. 生成大纲
4. 撰写章节
5. 复核与合并
6. 正式发布

每个阶段可显示：

- `pending`
- `active`
- `done`
- `failed`

### C. 中央主画布

这是最重要的区域，应该随着阶段切换展示不同类型的“可视化中间产物”。

建议按阶段展示：

- 理解资料阶段：文件卡片、文件摘要、资料标签
- 生成大纲阶段：章节列表、章节目标、预计结构
- 撰写章节阶段：章节草稿卡片、草稿片段、当前字数
- 合并发布阶段：整本文档片段、发布前检查结果

### D. 右侧实时动态区

显示滚动事件流：

- “已读取《高数期末重点.pdf》”
- “已生成 6 章大纲”
- “第 2 章开始撰写”
- “第 2 章草稿已生成，约 1260 字”
- “整本合并检查完成”

### E. 底部陪伴区

轮播展示：

- 你知道吗
- 学习小贴士
- 名人名言

这部分优先前端本地静态内容，不阻塞主链路。

---

## 5. 关键设计决策

## 5.1 使用 SSE，而不是只靠 polling

推荐口径：

- **SSE 负责“实时在变的过程体验”**
- **polling 负责“断线恢复 / 页面重进恢复 / 最终状态兜底”**

原因：

- DocGen 是长任务，用户更需要实时反馈
- 当前后端已经有 SSE 工具和 Planner SSE 经验
- 相比 WebSocket，SSE 更简单，更适合单向状态流
- polling 不该删除，因为它更适合刷新恢复和容错

### 结论

> 不是用 SSE 替掉 polling，而是做成 “SSE 主体验 + polling 兜底恢复”。

---

## 5.2 不做 raw token streaming，先做 snapshot streaming

不建议第一阶段就像聊天那样流 token：

- DocGen 是多章并行 fan-out，不像单线程写一段回复
- 原始 token 流顺序不稳定，前端难以解释
- 真实用户更关心“第几章开始了、生成了什么”，而不是底层 token

推荐第一阶段流式内容：

- 阶段状态
- 文件处理状态
- 大纲 snapshot
- 章节草稿 snapshot
- 最近事件
- 发布结果

也就是：

> **先流“可解释快照”，不要先流“原始 token”**。

---

## 5.3 保留后台任务模型，不把 DocGen 改成请求内同步长跑

当前 DocGen 是后台任务，这个方向不应推翻。

推荐结构：

- `POST /knowledge/build`：继续负责受理构建
- 新增一个 DocGen SSE 订阅接口：监听当前 build session 的事件流
- 后台任务把事件写入 runtime store / event stream
- SSE 接口负责把事件推给前端

这样有 3 个好处：

1. 页面刷新后还能重新订阅
2. 构建任务与 HTTP 生命周期解耦
3. 失败恢复、重进页面、后续多端观察都更自然

---

## 6. 推荐技术方案

## 6.1 总体结构

推荐采用“两层状态面”：

### 第一层：当前快照

继续保留现有：

- `build status`
- `build preview`
- `build metrics`

用途：

- 页面恢复
- 刷新恢复
- SSE 断开后的 fallback

### 第二层：事件流

新增 DocGen event stream：

- 每次关键阶段推进时追加一条事件
- 每次有重要中间产物时追加一条 snapshot 事件
- SSE 读取这些事件并增量推送

用途：

- 实时 UI
- 动画驱动
- 最近进展列表

---

## 6.2 推荐新增的持久化结构

建议在 `knowledge_markdowns/_build/` 下新增轻量 runtime 文件：

```text
knowledge_markdowns/_build/
  status.json
  manifest.json
  events.jsonl
  outline_snapshot.json
  chapter_preview/
    chapter_01.json
    chapter_02.json
  merged_preview.md
```

说明：

- `events.jsonl`
  - 只写轻量事件，适合 SSE 顺序读取
- `outline_snapshot.json`
  - 用于显示“当前大纲”
- `chapter_preview/*.json`
  - 每章一个轻量预览，不直接暴露完整草稿
- `merged_preview.md`
  - 用于展示整本合并片段

不要求所有文件第一阶段都上，但 `events.jsonl` 和 `outline_snapshot.json` 应优先落地。

---

## 6.3 推荐新增的 SSE 接口

推荐新增：

```text
GET /api/v1/subjects/{subject}/knowledge/build/stream?build_session_id=...
```

也可以接受：

```text
GET /api/v1/subjects/{subject}/knowledge/docs/stream?build_session_id=...
```

但更建议挂在 `build/stream`，语义更清晰。

### 入参

- `subject`
- `build_session_id`
- 可选 `last_event_id`

### 返回

- `text/event-stream`

### 连接语义

- 如果 build 仍在进行：持续推送事件
- 如果 build 已结束但有历史事件：可以快速补发最近状态后关闭
- 如果 build session 不存在：返回结构化错误

---

## 7. 前端改造建议

## 7.1 BuildView 不推倒，升级为 Build Theater

当前 `BuildView` 已经有不错的等待页骨架，不建议推倒重做。

建议改造为：

- 保留现有：
  - timeline
  - material pipeline
  - chapter progress
  - research sources
- 新增：
  - outline preview panel
  - chapter draft board
  - build live feed
  - did-you-know carousel

### 推荐组件拆分

```text
BuildExperienceShell
BuildStageRail
BuildLiveFeed
BuildOutlinePreview
BuildChapterDraftBoard
BuildMergedPreview
BuildDidYouKnow
```

---

## 7.2 did-you-know / 名人名言实现建议

这部分不建议依赖后端。

推荐第一阶段直接做成本地静态内容：

- 文件位置建议：
  - `frontend/src/components/knowledge-docs/buildTrivia.ts`
  - 或 `frontend/src/lib/buildTrivia.ts`

内容类型建议混合：

- 学习科学小知识
- 资料解析 / 构建过程说明
- 名人名言

轮播规则建议：

- 每 12-18 秒切换一条
- 页面失焦时暂停
- 构建完成或失败后停止轮播

### 原则

> 这部分是“陪伴层”，不应该占用任何后端算力，也不应该影响主链路稳定性。

---

## 8. 分阶段实施建议

## Phase 1：先让等待页“活起来”

目标：

- 仍然保留现有 polling
- 增加更丰富的当前 preview 数据
- 前端等待页从“进度条”升级成“多面板构建剧场”
- 加入 did-you-know

后端最小改动：

- 扩充 `KnowledgeBuildPreviewResponse`
- 在关键节点增加更多 snapshot 写入

前端最小改动：

- 重构 `BuildView`
- 加入 outline / chapter draft / tips 面板

这是最低风险、最快能上线的一步。

## Phase 2：补上 DocGen SSE 主链

目标：

- 新增 DocGen SSE 订阅接口
- 前端优先走 SSE，polling 作为 fallback
- 让事件驱动 recent feed、章节状态和预览更新

后端改动：

- 新增事件 schema
- 新增事件写入机制
- 新增 SSE 订阅 endpoint

前端改动：

- 新增 stream client
- 新增 event reducer / 状态合并器

## Phase 3：做成可恢复的真实实时体验

目标：

- 页面刷新后重建当前 build theater
- 支持 `last_event_id`
- 支持更稳定的 chapter preview 增量更新
- 把 graph sync / publish 也纳入最终可视化

---

## 9. 推荐第一批后端事件

第一批建议不要太多，先够用：

1. `build.accepted`
2. `build.stage_changed`
3. `build.file_snapshot`
4. `build.outline_snapshot`
5. `build.chapter_started`
6. `build.chapter_preview`
7. `build.chapter_completed`
8. `build.merge_preview`
9. `build.published`
10. `build.error`
11. `build.done`
12. `build.heartbeat`

详细字段建议见补充文档：`20b_docgen_sse_event_protocol.md`

---

## 10. 风险与注意事项

### 10.1 不要把所有中间产物都直接往 SSE 里塞

SSE 适合事件和轻量快照，不适合超大 Markdown 块。

正确方式：

- SSE 发“章节预览已更新”
- 真正的大对象存在 `_build/` snapshot 中
- 前端必要时按需取当前快照

### 10.2 并行章节写作要避免 UI 顺序抖动

DocGen 是 fan-out 的，章节完成顺序不一定等于章节顺序。

UI 应按 `chapter_index` 排序显示，而不是按事件到达顺序插入。

### 10.3 不要让 quotes / tips 进入后端核心链路

它们的价值是提高等待体验，不是业务真相。

所以：

- 可以前端静态
- 不需要后端存储
- 不需要进入 `build_preview`

### 10.4 不要在第一阶段硬做 token streaming

那会把问题从“体验不够好”升级成“并行写作的流式协议很复杂”。

---

## 11. 验收标准

满足以下条件，才算这一轮设计真正落地：

1. 用户开始构建 1-2 秒内能看到至少一条具体动态，不再只有空进度。
2. 用户能看到：
   - 资料卡片
   - 当前大纲
   - 至少一个章节预览
3. 等待页刷新后能恢复当前状态，不会完全白板。
4. 构建时间超过 1 分钟时，用户依然能持续看到内容变化。
5. 前端等待页有至少一组 did-you-know / 名人名言轮播。
6. SSE 断开时页面不会崩，polling 仍能兜底。

---

## 12. 一句话结论

这次改造的正确方向不是“把进度条做得更炫”，而是：

> **把知识文档构建过程变成一个能被用户看见、理解、信任、愿意等待的实时剧场。**
