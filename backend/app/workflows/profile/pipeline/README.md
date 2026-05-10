# Profile Pipeline 兼容层说明

最后更新：2026-05-11

`profile/pipeline/` 现在只是旧路径兼容层，不再是新的功能落点。

新的真实 lane：

```text
profile/update/       # 判卷后画像更新，写掌握度/复习/画像摘要
profile/snapshot/     # Profile 页只读快照，组装 mastery overview / course profile / user profile
profile/study_plan/   # 主动学习计划，生成复习+练习+伴读的执行建议
```

`pipeline/graph.py` 会继续导出旧名称：

- `build_profile_pipeline_graph`
- `run_profile_pipeline_workflow`
- `create_profile_initial_state`

这些名称都转发到 `profile/update`，避免旧 import 立即断掉。

新代码不要继续往 `pipeline/` 里加业务链路。确实需要共享 helper 时，先判断是否已经有两个以上 lane 真实复用；如果是，再按 `workflows/README.md` 的规则提升到 `profile/common/`。
