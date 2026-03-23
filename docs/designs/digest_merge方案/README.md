# Digest Merge 方案

## 1. 这份方案解决什么问题

当前 `knowledge/build` 的对外语义已经像“一个 build 同时产出知识文档和知识图谱”，但内部实现还不是这样。

- `backend/app/api/knowledge.py` 里的 `POST /api/v1/subjects/{subject}/knowledge/build` 会同时起两个后台任务。
- `backend/app/services/knowledge/digest_service.py` 会分别调用 `run_docgen_background(...)` 和 `run_graph_digest_background(...)`。
- `backend/app/workflows/digest/runtime.py` 里 `run_docgen_workflow(...)` 与 `run_graph_digest_workflow(...)` 完全独立运行。

这意味着它们现在只是“同时开始”，不是“协同构建”。

真正的问题不是入口不统一，而是下面这几件事还没有打通：

- 相同原始资料被两套流程各自读取、清洗、切分。
- docgen 按“文件/章节”思考，KG 按“chunk/实体”思考，中间没有共享 identity。
- 文档大纲不会利用图谱候选主题；图谱解析也不会利用文档章节规划。
- 构建结束后没有做文档与图谱的一致性校验，因此二者会各自“看起来像完成了”，但并不互相印证。

## 2. 核心结论

本方案的核心判断只有一句话：

**不要把 docgen 和 KG 粗暴合并成一条大串行 LangGraph；要做成“单次 build 下的协调型双车道构建”。**

更具体地说：

- 对外仍然保留一个 `build`。
- 对内新增一个统一的 `digest build session` 协调器。
- 真正合并的是“共享准备层、共享 chunk identity、共享 hint、共享一致性校验”，不是把两条图强行串成一条慢图。
- 所有协作都必须是软依赖、限时等待、局部补偿，不能把 docgen 和 KG 的主路径互相卡死。

## 3. 文档索引

- [01_现状拆解.md](./01_现状拆解.md)
  逐节点拆解当前 docgen / KG 两条 LangGraph，说明现在为什么只是并发，不是协同。
- [02_协同构建设计.md](./02_协同构建设计.md)
  给出推荐架构：共享准备层、双车道并行、软协作、最终一致性修复，以及需要改哪些节点。
- [03_迁移与评测计划.md](./03_迁移与评测计划.md)
  给出低风险迁移步骤、性能与质量指标、开关设计以及红线。

## 4. 一眼看懂版

```text
当前：
knowledge/build
  ├─ background task A -> docgen graph
  └─ background task B -> kg graph

目标：
knowledge/build
  └─ one digest build session
       ├─ shared prepare
       ├─ doc lane (parallel)
       ├─ kg lane  (parallel)
       ├─ bounded cross-check / local repair
       └─ publish / finalize
```

## 5. 方案边界

这份方案只讨论 `digest` 里“知识文档构建”和“知识图谱构建”的协同，不做下面几件事：

- 不重写 `curriculum` 的主流程，只保证它继续安全地挂在 KG finalize 后面。
- 不改前端协议。
- 不把 docgen 变成一个图谱查询器，也不把 KG 变成一个章节写作器。
- 不要求第一版就引入复杂的多机分布式编排；先在当前进程内事件总线 + 本地/subject 级工件存储上完成。

## 6. 推荐落地顺序

如果只看执行优先级，建议这样做：

1. 先做共享准备层，消除重复读文件、重复清洗、重复切分。
2. 再做共享 chunk identity 和中间工件契约，让两条 lane 至少“说的是同一份材料”。
3. 然后加中途软协作：文档给图谱 soft priors，图谱给文档 coverage hints。
4. 最后再加有预算上限的局部修复，而不是一开始就上全量双向重跑。
