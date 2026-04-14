# LangSmith 可观测性 — 待完成部分

> 最后更新：2026-04-14
>
> 已落地：4 个 tracing 入口、业务 ID 统一、node metadata 输出、lane summary 聚合。
> 详细实现文档：`backend/app/workflows/LANGSMITH.md`、`backend/app/workflows/TRACKED_STEP.md`。
> 本文档只保留待建设的 dashboard 和待补强的观测点。

---

## 1. 待建设 Dashboard

### Dashboard 1：Docs Lane 总览

- build 总耗时、节点耗时占比、失败率

### Dashboard 2：模式对比

- `sprint / systematic` 平均耗时、平均字数、平均练习数、平均媒体数

### Dashboard 3：Research 质量

- `requested_profile / applied_profile` 对比
- local / edu_web / academic / general 命中分布
- `gaps_remaining`、`curated_source_count`

### Dashboard 4：LLM tier 分布

- `reason / primary / light` 占比
- fallback 频率
- 哪些节点最容易降级

### Dashboard 5：Asset sidecar

- Mermaid / image 成功率
- interactive / animation 调用频率
- asset 对总耗时的影响

---

## 2. 待补强的观测点

- research round 收益衰减可视化
- gap 类型统计（按学科/模式维度）
- cache 命中率按学科 / profile / lane 的聚合视图
- cache 对总耗时和 round 数的真实收益分析
- animation 真正接入后的独立观测（当前仅预留位）

---

## 3. 验收标准（不变）

1. 打开 LangSmith，能一眼看懂主流程与章节 fan-out
2. 任意一章的 research round、writer、asset 都能独立定位
3. 能对比 `requested_profile` 和 `applied_profile`
4. 能比较不同课程模式、不同 research 深度、不同 asset 策略的效果
