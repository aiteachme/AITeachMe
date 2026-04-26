# AITeachMe DocGen Build Workspace: SSE 协议与状态机设计

最后更新：2026-04-21

本文档浓缩了知识文档建设 (DocGen) 的前后端状态同步与 SSE 事件协议规划。为了支撑高级的“剧场化”构建工作台，我们需要确保数据的**实时性、可靠性与易解析性**。

---

## 1. 核心架构：SSE 主驱动 + Polling 兜底恢复

我们的目标是让用户“始终看到实时的内容”，同时能够在刷新或掉线后无损恢复。

- **SSE (Server-Sent Events)** 负责：**增量、实时**的动画驱动与微小状态更新（如一句话日志、章节字数跳动）。
- **Polling (轮询 API)** 负责：**全量、兜底**的快照同步。前端首次进入或断网重连时，拉取完整的 `build_preview` 恢复大局。

---

## 2. SSE 事件流协议设计

接口建议设为：`GET /api/v1/subjects/{subject}/knowledge/build/stream?build_session_id=...`

SSE 只流出**轻量级快照**与**状态切换事件**，坚决不流出大段 Token（避免乱序与前端解析成本）。

### 2.1 推荐承载的 5 大核心事件 (Event Types)

统一外层 Envelope：
```json
{
  "event_id": "evt_xxx",
  "timestamp": "2026-04-21T12:00:00Z",
  // 具体的业务负载将合并在此层
}
```

#### 事件 1：`stage_changed` (大阶段切换)
用于驱动左栏 `BuildStageRail`。
```json
{
  "event": "stage_changed",
  "stage_id": "drafting_chapters",
  "stage_label": "发散撰写章节",
  "progress_pct": 45
}
```

#### 事件 2：`artifact_snapshot` (关键核心产物更新)
用于驱动中栏 `BuildArtifactCanvas` 的画面突变。避免传大对象，只传渲染所需的摘要树。
```json
{
  "event": "artifact_snapshot",
  "type": "outline", // 或 "insights", "draft_matrix", "merged_preview"
  "payload": {
    "chapters": [
      { "id": 1, "title": "极限概念", "status": "generating", "words": 150, "concept_tags": ["无限逼近"] }
    ]
  }
}
```

#### 事件 3：`feed_log` (实时流日志)
用于驱动右栏 `LiveFeedList`，给用户高频（几秒一次）的安全感缓冲。
```json
{
  "event": "feed_log",
  "level": "info",
  "message": "正在解析《高等数学同济版.pdf》的第 15 - 30 页...",
  "icon": "search" // 提示前端渲染的图标建议
}
```

#### 事件 4：`source_engaged` (溯源关联)
用于驱动右栏下部的 `RelevantSources`。
```json
{
  "event": "source_engaged",
  "source_name": "高等数学同济版.pdf",
  "topic": "导数",
  "citation_index": 3
}
```

#### 事件 5：`build_completed` / `build_failed`
用于终结流，触发阅读页的平滑切换或错误大弹窗。

---

## 3. 前端状态管理 (State Management)

前端需要一个统一的 Hook：`useKnowledgeBuildWorkspace`，它在内部同时管理 Polling 数据和 SSE 流数据，并对外暴露唯一可信的 State。

```typescript
// 伪代码架构：
function useKnowledgeBuildWorkspace(subjectId: string, requestedAt: string) {
  // 1. 基础兜底：通过 React Query 轮询全局 Snapshot
  const { data: snapshot } = useQuery({ queryKey: ['doc_state', subjectId]... });

  // 2. 实时增量：订阅 SSE
  const [liveEvents, setLiveEvents] = useState([]);
  const [liveArtifact, setLiveArtifact] = useState(null);

  useEffect(() => {
    const eventSource = new EventSource(`/api/.../stream`);
    eventSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      // Reducer: 合并 SSE 增量到本地 State
      dispatch(data);
    };
    return () => eventSource.close();
  }, [subjectId]);

  // 3. 智能合并：以 Snapshot 为基底，以 SSE 为最新覆盖
  const derivedState = useMemo(() => {
    return mergeDeep(snapshot, liveArtifact);
  }, [snapshot, liveArtifact]);

  return {
    stage: derivedState.stage,
    artifactType: derivedState.current_artifact_type,
    artifactPayload: derivedState.payload,
    feed: liveEvents,
    progress: derivedState.progress
  };
}
```

## 4. 后端落地的配合路径

后台工作流（DocGen LangGraph）的改造极小，只需在每个节点（Node）的末尾或关键循环中：
1. 更新数据库中的 `build_preview` 字段（供给 Polling 用）。
2. （新增）往 Redis PubSub 或消息队列丢一条 Event（供给 SSE 推送用）。

通过这种状态机设计，我们可以**解耦大段落生成（交由异步存储）与状态可视化（交由 SSE 事件通道）**，确保即使用户查看包含数万字的复杂文档，前端内存也不会因为流式读取大文本而溢出。
