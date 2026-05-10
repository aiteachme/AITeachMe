# Profile 模块说明

最后更新：2026-05-11

`profile/` 负责掌握度更新、复习调度、画像快照和基于画像的学习建议。

当前 canonical 结构：

```text
profile/
  __init__.py
  README.md
  update/          # 判卷后画像更新，写掌握度/复习/画像摘要
  snapshot/        # Profile 页只读快照，组装 mastery overview / course profile / user profile
  study_plan/      # 主动学习计划，生成复习+练习+伴读的执行建议
  common/          # 多条 profile lane 共享的 tracing / routing 辅助
  pipeline/        # 旧路径兼容层，不再新增业务
```

`study_plan` 不叫 `planning`，是为了避免和 `digest/planner` 混淆：

- `digest/planner` 规划资料消化和知识文档结构。
- `profile/study_plan` 规划用户接下来怎么复习、练习和复盘。

当前公开运行入口：

- `run_profile_update_workflow(...)`：判卷完成后触发，持久化更新掌握度、复习任务和画像摘要。
- `run_profile_snapshot_workflow(...)`：Profile 页读取时触发，只读生成 mastery overview / course profile / user profile。
- `run_profile_study_plan_workflow(...)`：基于画像生成主动学习计划，不写 DB、不替代 Digest Planner。

兼容入口：

- `run_profile_pipeline_workflow(...)` 仍可用，但只是转发到 `run_profile_update_workflow(...)`。

LangSmith root trace：

- `profile.update`
- `profile.snapshot`
- `profile.study_plan`

三条真实 lane 的节点都通过 `common/ProfileNodeTracer` 写入 `node_description`、读写对象和 state 输入输出，保证 LangGraph 图和 LangSmith node span 里的排障信息一致。

模块根只保留稳定导入面与 README，不恢复 `application/`、`events.py`、`exports.py` 这类根层包装文件。
