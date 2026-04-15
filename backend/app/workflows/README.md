# Workflows 说明

最后更新：2026-04-15

`backend/app/workflows/` 是 AITeachMe 的业务编排层。这里负责把 ingest、digest、interact、examine、profile 这些核心引擎组织成真正可运行的 workflow。

## 先看什么

- 总体结构规范：[STRUCTURE.md](./STRUCTURE.md)
- 调试方式：[DEBUGGING.md](./DEBUGGING.md)
- LangSmith 约定：[LANGSMITH.md](./LANGSMITH.md)
- 进度事件约定：[PROGRESS.md](./PROGRESS.md)

## 当前 canonical 链路

- `ingest/fast_parse`
- `ingest/deep_enhance`
- `digest/planner`
- `digest/docgen`
- `digest/knowledge_graph`
- `digest/unified`
- `interact/chat`
- `examine/question_build`
- `examine/exam_grade`
- `profile/pipeline`

## 最重要的调用入口

上层服务优先依赖模块级稳定入口：

```python
from app.workflows.ingest import run_parse_file_workflow
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest.planner import run_build_planner_workflow
from app.workflows.interact import stream_chat_workflow
```

如果是调试图结构，再进入对应链路目录看 `graph.py`。

## 当前模块角色

- `ingest`
  把原始文件转成标准化 Markdown 与素材资产。
- `digest`
  生成 confirmed plan、知识文档和知识图谱。
- `interact`
  负责对话式伴读与教学化流式输出。
- `examine`
  负责组卷与判卷。
- `profile`
  负责掌握度、复习计划和画像刷新。

## 目录边界

推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

具体结构规则不要再以 README 为准，请统一看 [STRUCTURE.md](./STRUCTURE.md)。
