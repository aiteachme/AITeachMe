# Ingest 模块说明

最后更新：2026-04-16

`ingest/` 负责把上传后的原始文件转换成后续 `digest` 可消费的标准化 Markdown 与资产。

## 当前 canonical 结构

```text
ingest/
  __init__.py
  README.md
  fast_parse/
  deep_enhance/
  parsing/
  recovery.py
```

说明：

- `fast_parse/` 是同步快速解析链路
- `deep_enhance/` 是后台增强链路
- `parsing/` 是两条链路共享的解析实现层
- `recovery.py` 负责服务启动后的增强任务恢复

## 对外入口

上层服务继续使用：

```python
from app.workflows.ingest import run_parse_file_workflow
```

如果只调链路图，再看：

- `app.workflows.ingest.fast_parse.graph`
- `app.workflows.ingest.deep_enhance.graph`

## 迁移说明

- 模块根 `graph.py / runtime / state.py` 仍作为稳定兼容入口保留
- 真实链路已经是 `fast_parse/` 和 `deep_enhance/`
- 共享解析逻辑直接从 `parsing/` 进入；不要再新增只做转发的 `_shared/` 空门面

## 一句话总结

ingest 是“模块层统一入口 + 两条真实链路”的结构：模块根负责兼容，对内执行以 `fast_parse/` 和 `deep_enhance/` 为准。
