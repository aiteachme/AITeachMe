## 十一、待确认问题

> 原则：只保留真正影响产品路径、算法深度或跨引擎合同的问题。
> 最后更新：2026-04-13

---

## 11.1 已经不再是开放问题的默认结论

下面这些现在应视为当前默认结论，而不是继续争论的主题：

| 主题 | 当前默认 |
| --- | --- |
| 三层边界 | `shared/infra / teaching / workflows` 已固定 |
| 扩展模型 | `tool / skillpack / toolpack` 三分模型成立 |
| workflow tracing | 默认只保留 `run_state_graph / workflow_tracer(...).node(...) / @traceable_run / tracked_step` |
| DocGen runtime 落点 | 继续放 `workflows/digest/docgen/runtime` |
| `retrieval_profile` 是否进执行链 | 已进入 planner/docgen 与 trace，不再是开放问题 |
| interactive HTML 是否有最小主线 | 已有最小 sidecar 模板链，不再是“要不要做”的问题 |

---

## 11.2 现在真正还开放的关键问题

### 1. 前端要不要显式暴露 `course_type` / `retrieval intent`

当前推荐：

- `course_type` 继续默认由 planner 推断
- 前端只在必要时暴露简单模式切换
- `retrieval_profile` 不直接暴露底层名称，而是映射成用户能理解的研究深度/资料偏好

仍待拍板的，是前端到底要暴露到多细。

### 2. research cache 的持久化边界怎么定

当前推荐：

- 优先缓存检索结果、URL 读取结果、压缩结果
- 先做 workflow-safe、本地可控的缓存
- 不把用户上传资料内容粗暴沉淀成长期公用语料

仍待拍板的，是缓存放置层、过期策略和跨用户隔离粒度。

### 3. `interactive_html` 的前端渲染契约做到多强

当前推荐：

- 继续保持 backend-first 的最小模板链路
- 前端只保证 KaTeX / 基础样式 / 安全渲染边界
- richer widget 作为后续增强，而不是现在就做复杂交互框架

仍待拍板的，是前端最终支持到“简单 HTML 模板”还是“更强交互组件协议”。

### 4. 什么时候把 `selected_skillpacks` 扩到 Interact / Examine

当前推荐：

- 先把 Digest 的合同做稳
- 再把 skillpack 语义逐步扩到 Interact / Examine
- 不要为了统一而过早把所有引擎同时复杂化

仍待拍板的，是先接 Interact 还是先接 Examine，以及最小共享字段范围。

### 5. animation 进入主线的准入标准是什么

当前推荐：

- 继续保留 `animation` 作为 contract / trace 预留位
- 只有在 richer image / interactive sidecar 已稳定后，再考虑真正接入 animation

仍待拍板的，是 animation 的教育价值验收标准和首批适用学科。

### 6. 本地教育语料库的建设节奏

当前推荐：

- 先做少数学科的高质量试点
- 优先做授权明确、可追溯来源、可稳定复用的教育条目
- 不把商业资料原文沉淀为长期底仓

仍待拍板的，是第一批学科和语料生产/审核流程。

---

## 11.3 需要持续验证、但不阻塞当前推进的问题

- 不同学科下 `coverage_score` 的阈值应如何设定
- `sprint / systematic` 的 research round cap 是否还需按学科细分
- `SourceCurator` 的来源分类与教育权重是否足够稳定
- `interactive_html` 对总时延和学习价值的真实收益
- `practice layer` 的哪类题目最能提升课程质量与留存
- Interact 的长对话压缩策略是否需要更强的 summarization budget

---

## 11.4 一句话结论

当前真正阻塞执行的，已经不再是“大架构怎么定”，而是少数产品取舍和跨引擎合同问题。
其余方向都可以继续按当前推荐方案推进。