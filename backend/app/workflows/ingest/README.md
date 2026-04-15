# Ingest 模块说明

最后更新：2026-04-15

`ingest/` 是资料进入系统后的第一站。

它负责把原始文件转成后续 `digest` 可以消费的标准化 Markdown 和素材资产。

## 模块定位

`ingest` 现在按两条链路组织：

1. `fast_parse`
   快速解析，尽快产出第一版 Markdown
2. `deep_enhance`
   深度增强，在后台补充 OCR / 质量增强结果

这两条链路共同构成 ingest 模块，但它们不是同一张 graph。

## 目录结构

```text
ingest/
  __init__.py
  README.md
  graph.py
  state.py
  runtime/
  events.py
  exports.py
  prompts/
  parsing/
  fast_parse/
  deep_enhance/
```

其中：

- `graph.py` / `state.py`
  是模块层聚合与兼容导出
- `runtime/`
  是模块层执行入口与共享 helper
- `fast_parse/`
  是第一条链路
- `deep_enhance/`
  是第二条链路

## 稳定入口

上层继续优先依赖：

```python
from app.workflows.ingest import run_parse_file_workflow
```

如果只是调图或独立调试，再看：

- `app.workflows.ingest.fast_parse.graph`
- `app.workflows.ingest.deep_enhance.graph`

## 一句话总结

`ingest` 现在是一个“模块层 + 两条链路层”的结构：模块层保留稳定入口，链路层分别承接 `fast_parse` 和 `deep_enhance` 的 graph、state 与节点定义。

