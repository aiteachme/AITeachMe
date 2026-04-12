## 十一、待确认问题

> 原则：只保留真正会影响算法与产品路径的问题，其余默认按推荐方案执行。
> 最后更新：2026-04-10

---

## 11.1 可以直接按推荐方案执行的默认决策

| 主题 | 推荐默认 |
| --- | --- |
| 课程模式 | 考试/冲刺默认 `sprint`；学科/系统学习默认 `systematic` |
| 文风 | `sprint -> encouraging/casual`；`systematic -> professional` |
| 系统课字数 | 默认目标 10000-15000 |
| 检索优先级 | 用户资料 > 本地语料 > 教育 Web > 学术 > 通用 Web |
| research 算法 | 单章微循环，`sprint` 最多 1 轮，`systematic` 最多 2 轮 |
| canonical memory | `app.shared.infra.memory` |
| 富媒体策略 | Mermaid 优先，image 次之，interactive/animation 后置 |

---

## 11.2 仍需拍板的关键问题

### 1. 前端是否要明确暴露“课程格式”选项

要不要让用户显式选择：

- 速成课讲义
- 系统课讲义
- 精简系统课

推荐默认：

- 先由 Planner 自动判断
- 前端只在必要时暴露简单二选一

### 2. 是否要在 Phase 4 就做交互 HTML

推荐默认：

- Phase 4 先把接口和 sidecar 做好
- 实际交互 HTML 只做极少量试点

### 3. 动画是否进入第一轮主线

推荐默认：

- 先只预留 `animation` 资产类型
- 真正的动画生成延后

### 4. 本地教育语料库第一批做哪些学科

推荐默认：

- 先做高数、线代、概率论
- 先把系统课跑深，再扩学科

### 5. 商业资料的长期沉淀策略

推荐默认：

- 用户上传资料只参与当前构建
- 不自动沉淀进系统长期语料库

### 6. 图片生成供应商

推荐默认：

- MVP 用现有国内兼容方案
- 后续再扩 DALL-E / Gemini 等

---

## 11.3 需要持续验证但不阻塞当前执行的问题

- `sprint / systematic` 的 sub query 数量是否还要细分学科
- `SourceCurator` 的教育权重是否足够
- 哪类 teaching block 最能提升课程质量和留存
- asset sidecar 对总时延的真实影响
- `systematic` 在不同学科上的合理字数上限
- `shared/infra/mcp.py` 何时升级为 `shared/infra/mcp/` 包
- `shared/infra/retrievers.py` / `reranker.py` 是否要并回 `shared/infra/search/`
- `shared/infra/strategies.py` 是否继续保留在 infra，还是迁到 `teaching` 或 `workflows/interact`

---

## 11.4 一句话结论

当前真正阻塞执行的，已经不是架构方向，而是少数产品取舍。
算法和主线重构可以继续推进，不需要再因为次级细节停住。

