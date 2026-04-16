# 21. Planner Deep Research 风格改造计划

最后更新：2026-04-16

## 一句话结论

Planner V3.2 现在已经按“先预览、再探测、再合成”的方向落地，并补上了真正的 reason 模型路由、few-shot 示例合同和前端 Markdown 正确渲染。

## 当前最终流程

```text
prepare_material_context
  -> generate_plan_preview
       ├─ stream_plan_sketch
       └─ extract_learning_intent
  -> probe_supporting_evidence
  -> compose_plan_contract
  -> finalize_plan_contract
```

## 当前实现重点

### 1. 显式模型选择

- `stream_plan_sketch`：`task_type=TaskType.REASONING`，`model="reason"`
- `compose_plan_contract`：`task_type=TaskType.REASONING`，`model="reason"`
- `extract_learning_intent`：`task_type=TaskType.DOCGEN_LIGHT`，`model="primary"`

底层 `llm_support` 不再通过 `TaskType` 推导模型。`TaskType` 只负责温度、超时、重试和观测归类；模型选择统一通过 `model=` 读取 `settings.models.*`。

### 2. Few-shot 示例

新增 `planner/prompts/examples.py`，并在以下步骤接入：

- `stream_plan_sketch`
- `compose_plan_contract`

已覆盖 4 组示例：

- sprint + exam-heavy
- sprint + concept-heavy
- systematic + textbook-heavy
- systematic + mixed-notes

### 3. Markdown 草稿合同

`stream_plan_sketch` 被强约束输出固定 Markdown 合同：

- `# 构建方案`
- `> 模式 / 一句话摘要`
- `## 研究任务`
- `## 暂定章节`
- `## 规划假设`
- `## 待确认点`

### 4. 前端正确渲染

Planner 预览已经不再靠字符串切割函数。

现在前端：

- 新增 `PlannerPreviewMarkdown.tsx`
- 复用 `MarkdownViewer`
- 新增 `variant="planner"`

因此：

- 标题、blockquote、ordered list、分节标题都能正确显示
- 不会因为 markdown 稍变导致任务列表解析失败

## 仍保留的兼容策略

- `DigestMaterialContext` 是主命名
- `SharedInputs` 仍作为 alias 保留
- 外部 API response 不变
- ConfirmedBuildPlan 合同不变
- 旧 `status/token/done` SSE 仍兼容

## 已验证

- `backend/tests` 全量通过
- `frontend` 执行 `npm run build` 通过
- `git diff --check` 通过
