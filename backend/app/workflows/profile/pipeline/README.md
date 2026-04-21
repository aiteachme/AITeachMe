# Profile Pipeline 链路说明

最后更新：2026-04-15

`profile/pipeline/` 是 profile 模块的 canonical lane。

目录角色：

- `graph.py`：pipeline 图入口
- `state.py`：状态定义
- `lib/`：掌握度、复习、画像、报告建议等 helper
- `prompts/`：画像相关 prompt 门面
- `nodes/`：节点门面

当前口径：

- LangGraph 定义、运行入口与 workflow export 已统一收口到 `pipeline/graph.py`
- API / schema 需要的画像与掌握度辅助对象统一从 `pipeline/lib/` 提供
