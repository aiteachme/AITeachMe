# Examine Question Build 链路说明

最后更新：2026-04-21

`examine/question_build/` 是 Examine 模块的题目构建链路。

目录角色：

- `graph.py`：题目构建图定义与运行入口
- `state.py`：图内状态合同
- `nodes/`：顶层图节点
- `lib/`：题目生成与结果整形 helper
- `prompts.py`：当前链路使用的 prompt 门面

当前口径：

- 该链路负责把知识单元与考试规格转换成结构化题目草稿。
- API 和上层 workflow 应优先通过 `app.workflows.examine` 或 `question_build.__init__` 的稳定导出进入。
