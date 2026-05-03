# Fast Parse 链路说明

`ingest/fast_parse/` 是 Ingest 透视引擎的单文件快速解析 workflow。

它负责把已经落库的 `RawFile` 转成 Digest 可消费的标准 Markdown 与资产目录。上传、列表、删除和批量派发不在这里，入口在 `ingest/intake/`。

## 公开入口

```python
from app.workflows.ingest import run_parse_file_workflow
```

图结构入口：

- `graph.py`：LangGraph 定义、初始 state、路由和单次运行入口。
- `state.py`：解析链路的 state 合同。
- `nodes/`：读取文件、分类、制定解析计划、执行解析、成功/失败收尾。
- `lib/`：解析运行时、生命周期、增强、恢复和持久化辅助。

## 当前流程

```text
load_raw_file
  -> compute_fingerprint
  -> classify_file
  -> plan_parse
  -> parse_file
  -> finalize_success / finalize_failure
```

Phase 2 后台增强由 `lib/enhance.py`、`lib/lifecycle.py` 和 `lib/recovery.py` 承接。它是解析完成后的异步补强，不是第二条 LangGraph lane。

## 边界

- 不处理 HTTP 上传。
- 不生成知识文档。
- 不构建知识图谱。
- 不做教学规划或出题。
- 不长期保存上传请求里的 OCR / MinerU token。

更完整的 Ingest 说明见上级 [README.md](../README.md) 和 [docs/workflows/ingest-engine.md](../../../../../docs/workflows/ingest-engine.md)。
