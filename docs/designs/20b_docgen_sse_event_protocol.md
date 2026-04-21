# 20b. 知识文档构建 SSE 事件协议草案

最后更新：2026-04-21

**状态**：规划中，未实现

本文件是 `20_docgen_live_build_experience.md` 的协议补充稿，定义 DocGen SSE 第一阶段建议采用的事件类型与 payload 草案。

---

## 1. 设计原则

DocGen SSE 不追求 token 级输出，而追求：

- 事件清晰
- 前端易渲染
- 支持断线恢复
- 可与 polling 共存

统一原则：

- `event` 表示事件类型
- `data` 只放当前事件需要的最小信息
- 大对象不直接塞进 SSE，优先写 snapshot 再发“已更新”事件

---

## 2. 连接接口

建议接口：

```text
GET /api/v1/subjects/{subject}/knowledge/build/stream?build_session_id=...&last_event_id=...
```

说明：

- `subject`：当前学科
- `build_session_id`：当前构建会话
- `last_event_id`：可选，用于断线后补发

响应：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

---

## 3. 通用 envelope

推荐每条事件都包含：

```json
{
  "event_id": "evt_000123",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:00:00Z"
}
```

其中：

- `event_id`：递增或可排序 id
- `build_session_id`：本轮构建会话
- `subject`：当前学科
- `timestamp`：事件产生时间

后续每个事件 payload 都在此基础上追加业务字段。

---

## 4. 第一阶段推荐事件

## 4.1 `build.accepted`

表示后端已接受构建请求。

```json
{
  "event_id": "evt_000001",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:00:00Z",
  "requested_at": "2026-04-21T12:00:00Z",
  "confirmed_plan_id": "plan_xxx",
  "planner_session_id": "planner_xxx",
  "digest_mode": "systematic",
  "accepted_files": [
    {
      "uid": "file_xxx",
      "filename": "高数重点.pdf",
      "status": "ready_for_digest",
      "parser_used": "markitdown"
    }
  ]
}
```

前端用途：

- 初始化顶部状态头
- 先展示“已纳入资料”

## 4.2 `build.stage_changed`

表示大阶段切换。

```json
{
  "event_id": "evt_000005",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:00:12Z",
  "stage": "preparing_docgen_context",
  "status": "running",
  "title": "正在理解资料",
  "description": "正在增强大纲、识别写作意图并摘要材料。",
  "progress_pct": 30
}
```

前端用途：

- 更新左侧阶段轨道
- 更新顶部状态头

## 4.3 `build.file_snapshot`

表示资料理解结果更新。

```json
{
  "event_id": "evt_000011",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:00:25Z",
  "files": [
    {
      "uid": "file_xxx",
      "filename": "高数重点.pdf",
      "summary": "覆盖极限、导数、积分三大块。",
      "page_estimate": 86,
      "parser_used": "markitdown",
      "tags": ["极限", "导数", "积分"]
    }
  ]
}
```

前端用途：

- 更新资料卡片区

## 4.4 `build.outline_snapshot`

表示章节大纲已形成或更新。

```json
{
  "event_id": "evt_000021",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:00:40Z",
  "plan_summary": "本次文档采用系统课结构，共 6 章。",
  "chapters": [
    {
      "chapter_index": 1,
      "title": "极限与连续",
      "objective": "建立极限语言与连续性基础。"
    },
    {
      "chapter_index": 2,
      "title": "导数与微分",
      "objective": "掌握变化率与局部线性化。"
    }
  ]
}
```

前端用途：

- 更新中央大纲板块
- 告诉用户“文档长什么样”已经定下来了

## 4.5 `build.chapter_started`

表示某一章进入研究 / 撰写。

```json
{
  "event_id": "evt_000031",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:01:10Z",
  "chapter_index": 2,
  "title": "导数与微分",
  "status": "drafting"
}
```

前端用途：

- 章节状态板置为“撰写中”
- 中央画布高亮当前章节

## 4.6 `build.chapter_preview`

表示某一章已有可展示草稿片段。

```json
{
  "event_id": "evt_000045",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:01:55Z",
  "chapter_index": 2,
  "title": "导数与微分",
  "status": "drafted",
  "word_count": 1280,
  "source_count": 6,
  "excerpt": "导数本质上描述函数在一点附近的瞬时变化率……",
  "latest_headings": ["导数定义", "几何意义", "求导法则"]
}
```

前端用途：

- 展示章节草稿卡片
- 更新章节字数 / 引用数 / 小标题

## 4.7 `build.chapter_completed`

表示某章已完成当前阶段。

```json
{
  "event_id": "evt_000052",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:02:20Z",
  "chapter_index": 2,
  "title": "导数与微分",
  "status": "completed",
  "word_count": 1630
}
```

## 4.8 `build.merge_preview`

表示整本合并预览已更新。

```json
{
  "event_id": "evt_000061",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:03:10Z",
  "latest_chapter_titles": ["极限与连续", "导数与微分", "积分与应用"],
  "draft_excerpt": "## 这份文档怎么读\n\n建议先看第一章的概念框架……"
}
```

前端用途：

- 更新整本预览卡
- 更新 `DocumentCanvas`

## 4.9 `build.event`

这是面向“实时动态区”的通用事件。

```json
{
  "event_id": "evt_000071",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:03:30Z",
  "stage": "merge_reviewed",
  "summary": "整本一致性检查完成，准备发布正式版。",
  "chapter_index": null,
  "title": null
}
```

前端用途：

- 右侧动态 feed

## 4.10 `build.hint`

用于 did-you-know / 学习贴士 / 名人名言。

第一阶段建议前端本地实现，不强依赖这个事件；但协议上可以预留。

```json
{
  "event_id": "evt_000081",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:04:00Z",
  "kind": "quote",
  "content": "教育不是灌满一桶水，而是点燃一把火。",
  "attribution": "叶芝"
}
```

## 4.11 `build.published`

表示正式发布成功。

```json
{
  "event_id": "evt_000091",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:05:10Z",
  "status": "completed",
  "updated_at": "2026-04-21T12:05:10Z",
  "chapter_count": 6,
  "doc_exists": true
}
```

## 4.12 `build.done`

表示 SSE 可正常结束。

```json
{
  "event_id": "evt_000099",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:05:11Z",
  "status": "completed"
}
```

## 4.13 `build.error`

表示构建失败。

```json
{
  "event_id": "evt_000098",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:05:10Z",
  "status": "failed",
  "stage": "generating_chapters",
  "error_code": "docgen_failed",
  "detail": "章节生成失败，请稍后重试。"
}
```

## 4.14 `build.heartbeat`

长任务保活事件。

```json
{
  "event_id": "evt_000050",
  "build_session_id": "bld_xxx",
  "subject": "subj_xxx",
  "timestamp": "2026-04-21T12:02:00Z"
}
```

建议每 10-15 秒一条即可。

---

## 5. 与 polling 的关系

SSE 负责：

- 实时动态
- 动画驱动
- 中间可视化

polling 负责：

- 页面刷新恢复
- SSE 断线 fallback
- 最终 published 文档读取

也就是说：

- `POST /knowledge/docs` 继续保留
- SSE 不替代文档读取接口
- 前端状态合并策略是：
  - 先用 polling 初始化
  - 再用 SSE 增量覆盖

---

## 6. 第一阶段落地优先级

建议优先实现以下 6 个事件：

1. `build.accepted`
2. `build.stage_changed`
3. `build.outline_snapshot`
4. `build.chapter_preview`
5. `build.event`
6. `build.done`

这样就已经足够支撑一版很像“实时构建剧场”的体验。

---

## 7. 一句话结论

DocGen SSE 第一阶段最重要的不是“流很多”，而是：

> **只流最值得用户看到、前端也最容易解释的那部分过程。**
