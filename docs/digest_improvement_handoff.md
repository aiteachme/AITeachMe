# Digest Improvement Handoff

## 当前结论

Digest 的核心问题不是单一 prompt，而是系统性组合问题：

1. 题号/过程性标题污染主题，导致出现 `Question*` 假节点。
2. typed resolution 不完整，仍可能出现同名串线与错父节点。
3. curriculum 分桶和图谱骨架耦合不稳，容易单父节点塌缩。
4. 性能瓶颈主要在 embedding 复用、chunk 增量物化和聚类策略，而不是旧的 `chapter_priors`。

---

## 产品决策（已确认）

- 等待体验走轮询，不新增 digest 专用 SSE。
- API 继续“少接口、POST 优先”。
- 学习计划保持单接口：`POST /knowledge/study-plan`（读写合一、全量回包）。
- 知识宇宙优先稳定语义星图，不回到随机词云。

---

## 接口口径（当前）

### 保留

- `POST /api/v1/courses/{course}/knowledge/build`
- `POST /api/v1/courses/{course}/knowledge/docs`
- `POST /api/v1/courses/{course}/knowledge/overview`
- `POST /api/v1/courses/{course}/knowledge/study-plan`

### 删除目标（不再保留）

- 独立 `build-status` 接口
- `GET /study-plan`
- `PATCH /study-plan/checklist`

### `POST /knowledge/docs` 约定

- `build` 继续保持最小状态字段：
  - `status`
  - `requested_at`
  - `stage`
  - `error_message`
  - `draft_available`
- 可选附带等待期增强字段（不新增路由）：
  - `build_preview`（阶段描述、chunk 进度、样例节点/卡片、草稿摘录）
  - `build_metrics`（LLM 调用总数、平均时延、lane 计数）

---

## 已落地进展（本轮）

- 后端：`build_session_id` 打通至 docs / graph 独立构建状态，便于关联日志和 LLM 调用统计。
- 后端：`POST /knowledge/docs` 已返回 `build_preview` / `build_metrics`。
- 后端：LLM timeout 与失败日志增加 trace 字段（course/build_session_id/workflow/lane/node）。
- 前端：`DigestBuildPanel` 与 `KnowledgeDocsPage` 已接入 `build_preview` / `build_metrics`，等待期展示卡片、样例节点、草稿摘录与调用统计。
- 前端：修复了 `KnowledgeDocsPage.tsx`、`DigestBuildPanel.tsx` 的编码污染和语法断裂问题，`npm run build` 已通过。

---

## 后续最高优先级

1. 继续推进 KG 语义骨架与 typed resolution 的 P0 问题（`Question*`、单父节点塌缩、同名串线）。
2. 完成 embedding 复用与分桶聚类性能回归，目标常规构建尽量控制在 5 分钟内。
3. 用真实样本做回归验收：
   - 不再出现 `Question 1` / `Question bank` 作为主题树叶子。
   - 主题树不再大面积单父节点聚合。
   - 文档页与图谱页等待态都可感知且可持续反馈。

---

## 验证清单

- 后端：
  - `atm` 环境 `py_compile`
  - `from app.main import app` 导入
- 前端：
  - `npm run build`
  - 文档页构建等待态 / draft-live 切换 / 学习计划交互
  - 图谱页学习计划入口与语义星图可用
