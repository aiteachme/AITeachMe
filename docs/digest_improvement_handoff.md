# Digest Improvement Handoff

## 当前结论

Digest 的主问题已经明确，不再是单一 prompt 调整，而是四类系统问题叠加：

1. 题号和过程性标题污染语义主题，导致出现 `Question*` 假节点
2. typed resolution 不完整，仍可能出现名称串线
3. 图谱到 curriculum 的分桶骨架不稳定，容易塌成单父节点
4. 性能瓶颈主要在 embedding 复用、chunk 物化和聚类策略，而不是旧的 `chapter_priors`

---

## 已确认的产品决策

- 等待体验优先使用轮询，不新增 digest 原生 SSE
- 进度不追求后端精确值，前端允许基于已有响应自由生成假进度
- 知识宇宙优先做稳定语义星图，不做随机漂移词云，也不强推 Three.js 真 3D
- 学习计划两边都展示
  - 知识文档页：完整展示，主场景
  - 知识图谱页：简版展示或入口
- API 越少越好，知识相关接口优先统一为 `POST`

---

## 当前接口口径

### 保留

- `POST /api/v1/subjects/{subject}/knowledge/build`
- `POST /api/v1/subjects/{subject}/knowledge/docs`
- `POST /api/v1/subjects/{subject}/knowledge/overview`
- `POST /api/v1/subjects/{subject}/knowledge/study-plan`

### 删除目标

以下接口不应继续保留为设计目标：

- 独立 `build-status`
- `GET /study-plan`
- `PATCH /study-plan/checklist`

### 当前约束

- 文档页和图谱页等待态都复用 `POST /knowledge/docs`
- `build` 字段只需要最小状态集：`status / requested_at / stage / error_message / draft_available`
- `POST /study-plan` 统一承担“查询 + checklist 更新 + 返回全量”

---

## 代码实现进度

### 已做方向

- 知识图谱主视图已经转向稳定语义星图方案
- 学习计划面板已开始向单接口、全量回包模式收敛
- 构建进度面板已开始改成基于 `knowledge/docs` 的前端本地进度
- digest 设计文档已同步到“少 API、POST 优先”的口径

### 仍需确认 / 清理

- OpenAPI 导出与 Orval 再生成需要重新跑通
- 当前 working tree 里仍可能存在未完全清理的旧调用或未验证代码
- 需要继续做前后端编译校验，确认接口收缩后的真实可运行状态

---

## 当前最高优先级

1. 完成接口收缩后的残余代码清理
   - 去掉 build-status 独立调用链
   - study-plan 统一为单个 POST
2. 跑通 OpenAPI 导出和前端生成代码
3. 完成前后端验证
   - `atm` 环境 `py_compile`
   - `npm run build`
4. 用真实样本回归以下验收点
   - 不再出现 `Question 1` / `Question bank` / `第 1 题` 主题
   - 不再大面积单父节点塌缩
   - 语义星图稳定可用
   - docs 页学习计划与等待态正常

---

## 文档索引

- [05_digest_engine.md](./designs/05_digest_engine.md)
- [05a_digest_knowledge_document.md](./designs/05a_digest_knowledge_document.md)
- [05b_digest_knowledge_graph.md](./designs/05b_digest_knowledge_graph.md)

这些文档已经统一到当前口径：

- 少 API
- `POST` 优先
- docs 轮询承担等待态
- study-plan 单 POST
- 语义星图替代随机词云
