# Question Build 链路说明

最后更新：2026-04-15

`question_build/` 是 examine 的出题链路门面。

当前 canonical 文件：

- `graph.py`
- `state.py`
- `nodes/`
- `prompts/`
- `lib/`

迁移期说明：

- 真实实现仍有一部分在模块根 `question_build_workflow.py` / `question_builder.py`
- 新入口统一从 `question_build/` 目录暴露
