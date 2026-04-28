# Digest 模块说明

最后更新：2026-04-28

`digest/` 负责把原始学习材料组织成可教学、可生成、可追踪的知识产物。

## 当前目录

```text
digest/
  __init__.py
  README.md
  common/
  planner/
  docgen/
  kg_doc_sync/
```

## 各目录做什么

- `planner/`
  负责根据文件内容和历史对话生成 confirmed plan
- `docgen/`
  负责根据 confirmed plan 生成知识文档
- `kg_doc_sync/`
  负责知识文档和知识图谱的正式同步链路
- `common/`
  放跨 lane 共用能力，例如 events、exports、contracts、prepare、material profile、metrics、runtime config、file status、pedagogy
  以及 subject 级知识产物清理 `cleanup.py`

## 当前公开入口

上层优先使用稳定导入面，不直接从深层文件拼装：

```python
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest import run_graph_docs_sync_workflow
from app.workflows.digest.planner import (
    create_build_planner_session,
    run_build_planner_workflow,
)
```

## 目录约束

- 模块根只做聚合，不承载业务实现
- 新的 API-facing 用例必须进入具体 lane 或 `common/`
- 新 prompt 放各自链路 `prompts/`
- 新 helper 放各自链路 `lib/`
- 跨 digest lane 共享能力统一放 `common/`；KG 图谱同步、查询、总览和清理都归入 `kg_doc_sync/`
- `common/__init__.py` 不做 re-export；跨模块引用时按职责从 `common.models`、`common.prepare` 等具体文件导入
- lane 内部的 `lib/__init__.py`、`nodes/__init__.py`、`prompts/__init__.py` 不做导出壳；graph 和节点代码从具体模块导入
- 各链路自己的构建摘要放在对应链路 `lib/reporting.py`
- 不要再新增顶层伪链路，例如 `runtime.py`、`observability.py`

## 当前理解

当前 digest 的 canonical 主线是：

- `planner -> docgen`
- `docgen sidecar prefetch -> publish -> kg_doc_sync persist`

## 两条核心链路介绍口径

### DocGen：生成可教学的知识文档

DocGen 消费 Planner 已确认的 `confirmed_plan`，不重新推翻用户确认过的章节语义。
当前主线是：

```text
读取确认方案
-> 准备全局种子
-> 生成封面
-> 锁定章节标题
-> 确认骨架种子
-> 构建文档知识骨架
-> 生成章节执行简报
-> 组装最终章节任务
-> 生成章节草稿（LangGraph Send 按章 fan-out）
-> 增强章节内容
-> 启动 KG 预抽取 sidecar（可选、非阻塞、发布前不落库）
-> 复核章节内容（LangGraph Send 按章 fan-out）
-> 复核整本一致性
-> 记录复核回流动作
-> 合并检查整本文档
-> 同步锁定标题
-> 发布知识文档
```

对外讲的时候可以概括成：先冻结用户确认方案，再用轻量全局准备和章级并行生成正文，最后通过复核、有限局部修补、合并和发布产出可追踪的知识文档。

### KG Doc Sync：把知识文档同步成知识图谱

KG 同步的正式落库仍只消费 DocGen 发布后的知识文档和结构化产物，不再直接解析原始上传文件入图。
自动同步可以复用 DocGen 期间产生的 section 级预抽取缓存；缓存命中才复用，最终内容变更则补抽。
当前主线是：

```text
prefetch_extract（可选，DocGen sidecar，发布前不落库）
-> publish_gate
-> prepare
-> init_run
-> reuse_or_catchup extract（节点内部按章节 async gather + semaphore 并发）
-> persist
-> finalize
```

对外讲的时候可以概括成：DocGen 期间可提前抽取候选，发布后先校验最终文档版本与缓存，再对缺失或变更章节补抽，随后统一写入 `knowledge_unit`、`knowledge_edge` 和 `knowledge_graph_source_ref`，并用 `knowledge_graph_sync_run` 记录本轮图谱同步结果。

旧 `kg_file_ingest` 调试链路已经删除。知识图谱同步只保留 `kg_doc_sync`。
KG 同步编排按 `prepare -> init_run -> extract -> persist -> finalize` 拆在 `kg_doc_sync/nodes/`，
抽取、候选合并、增量写库等可复用实现位于 `kg_doc_sync/lib/`。

如果要看具体编排，优先进入各链路下的 `graph.py`、`state.py`；API-facing 构建入口优先看对应 lane 的 `lib/*lifecycle*.py`
