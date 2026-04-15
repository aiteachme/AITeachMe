# Digest 模块说明

最后更新：2026-04-15

`digest` 是当前 `workflows` 里最典型的“多链路模块”。

它不是一条单独的 graph，而是一组围绕知识加工与知识文档构建的链路集合。后续其他引擎如果要扩成多链路模块，可以优先参考这里。

## 1. 模块定位

`digest` 负责把 Ingest 产出的材料加工成更适合学习的结构化知识资产。

当前最重要的业务主链路是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

也就是两段：

1. `planner`
   先把目标、资料、限制整理成 confirmed plan
2. `docgen`
   再按 confirmed plan 真正执行知识文档构建

## 2. Digest 的标准分层

按当前规范，`digest/` 应理解为：

```text
digest/
  __init__.py           # 模块公共导入面
  README.md             # 模块说明
  graph.py              # 多链路 graph export 聚合
  runtime.py            # 多链路运行入口聚合
  state.py              # 多链路 state re-export
  events.py             # 模块级 typed events
  exports.py            # langgraph dev / studio 导出
  prompts/              # 模块级 prompts
  shared/               # planner/docgen 等共享 contract 与模型
  planner/              # 轻量链路示例
  docgen/               # 复杂链路示例
  kg/                   # 图谱链路
  curriculum/           # 课程结构链路
  unified/              # 跨链路编排
  build/                # 构建一致性/产物辅助
  observability/        # lane summary 与 token summary
```

这里最重要的规则是：

- 根目录 `graph.py / runtime.py / state.py` 是聚合层，不继续堆 planner/docgen 细节
- `prompts/` 是模块级资源层，不属于具体链路
- 真实业务实现应该下沉到 `planner/`、`docgen/`、`kg/`、`curriculum/`

## 3. 模块级 prompts 应该怎么放

当前 `digest` 已经基本符合这条规则：

```text
digest/prompts/
  planner_prompts.py
  docgen_prompts.py
  kg_prompts.py
  archetype_prompts.py
  prompts.py
```

后续继续统一时，遵循下面原则：

- `planner` 相关 prompt 继续放 `planner_prompts.py`
- `docgen` 相关 prompt 继续放 `docgen_prompts.py`
- 跨链路共用的 prompt 片段，再抽到共享 prompt 文件
- 不要把 prompt 再塞回 `planner/graph.py`、`docgen/nodes/*.py` 或 `docgen/runtime/*.py`

如果未来 `docgen` prompt 再明显膨胀，可以升级为：

```text
digest/prompts/docgen/
  writer.py
  research.py
  repair.py
```

但它仍然应该留在模块级 `prompts/` 下面。

## 4. `planner` 为什么适合文件组织

当前 `planner` 是一条轻量链路，适合继续保持“文件模式”。

当前结构：

```text
digest/planner/
  __init__.py
  runtime.py
  graph.py
  state.py
  models.py
  concept_grounding.py
```

它符合文件模式的原因：

- graph 很小，当前只有 `load_context -> ground_concepts -> draft_plan`
- 没有 `nodes/` 或 `runtime/` 子目录的必要
- 主要复杂度在 prompt 组织和 plan contract，而不是 node 数量
- 对外入口很清楚：`run_build_planner_workflow(...)`

因此当前对 `planner` 的建议是：

- 保持文件模式
- 不要为了“形式统一”强行拆出 `nodes/`
- 但如果后续出现第 4 个以上长期 node，或者出现 fan-out / chain-local runtime，再升级为文件夹模式

### `planner` 各文件职责

- `__init__.py`
  暴露 `run_build_planner_workflow` 和 plan contract 相关公共对象
- `runtime.py`
  对外运行入口，负责 context 和 graph invoke
- `graph.py`
  定义 planner graph、node builder、初始 state
- `state.py`
  定义 `BuildPlannerState`
- `models.py`
  维护 planner draft/plan payload 的结构合同
- `concept_grounding.py`
  维护规划前的概念 grounding 逻辑

## 5. `docgen` 为什么适合文件夹组织

当前 `docgen` 已经明显跨过“轻量链路”的界限，应该继续按“文件夹模式”维护。

当前结构：

```text
digest/docgen/
  __init__.py
  graph.py
  state.py
  publish.py
  nodes/
    load_context_node.py
    targeted_research_node.py
    collect_materials_node.py
    resolve_titles_node.py
    pedagogy_craft_node.py
    collect_drafts_node.py
    enrich_document_node.py
    inject_examine_node.py
    finalize_node.py
    common.py
  runtime/
    chapter_context.py
    query_planning.py
    writer.py
    assets.py
```

它符合文件夹模式的原因：

- 节点数量已经明显超过 4 个
- 有 `Send()` fan-out / fan-in
- 有独立的 research、writer、publish、assets sidecar
- 章节级写作和组装逻辑已经形成链路内部子层

因此当前对 `docgen` 的建议是：

- 保持文件夹模式
- 继续把 graph wiring、node 实现、chain-local runtime 分层
- `publish.py` 保持显式文件，不要硬塞进 `runtime/`

### `docgen` 各层职责

- `graph.py`
  只定义 graph、路由、fan-out send、初始 state
- `state.py`
  定义 `DocGenState`
- `publish.py`
  负责 staged outputs、manifest、最终发布
- `nodes/`
  每个 graph node 一文件
- `runtime/`
  章节上下文、子查询规划、writer、assets 等链路辅助执行逻辑

### `docgen` 后续可接受的增强

下面这些增强是符合规范的：

- 新增 `docgen/events.py`
  当 docgen 需要稳定链路级 typed events 时
- 新增 `docgen/contracts.py` 或 `docgen/models.py`
  当章节 contract、publish contract 继续增长时
- 把 `docgen/nodes/common.py` 中过重的逻辑迁到 `runtime/` 或 `services/`

## 6. Digest 里最明显的问题

当前最明显、也最值得优先统一的问题有 3 个：

1. `digest` 已经是多链路模块，但之前缺少模块级 README，导致“根目录聚合层”和“链路实现层”的边界不够清楚。
2. `planner` 和 `docgen` 的组织方式已经明显不同，但之前没有规范解释“为什么一个用文件、一个用文件夹”。
3. `prompts` 实际上已经放在模块层，但这个规则没有被正式写下来，后续很容易继续出现 prompt 到处散落的问题。

这些都是结构级问题，属于值得先统一的“重大问题”。

## 7. 后续其他链路怎么套这套规范

对 `digest` 里后续新链路，建议按下面规则判断：

- 轻量链路：
  先按 `planner` 的文件模式起步
- 复杂链路：
  直接按 `docgen` 的文件夹模式建设
- 模块共享资源：
  放到 `digest/prompts/`、`digest/shared/`、`digest/observability/`
- 模块聚合入口：
  放到 `digest/__init__.py`、`digest/runtime.py`、`digest/graph.py`

一句话版：

```text
planner = 文件模式样例
docgen  = 文件夹模式样例
prompts = 模块级资源
digest 根目录 = 聚合层，不是实现垃圾桶
```

