# Profile Pipeline 链路说明

最后更新：2026-04-15

`profile/pipeline/` 是 profile 模块的 canonical lane。

目录角色：

- `graph.py`：pipeline 图入口
- `state.py`：状态定义
- `lib/`：掌握度、复习、画像、报告建议等 helper
- `prompts/`：画像相关 prompt 门面
- `nodes/`：节点门面

迁移期说明：

- 真实节点逻辑仍主要在模块根 `profile.graph` 中
- 新的导出面和 LangGraph 入口统一走 `pipeline/`
