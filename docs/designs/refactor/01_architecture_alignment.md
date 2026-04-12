## 一、三项目架构对齐

> 最后更新：2026-04-13
> 目标：回答“我已经有什么、真正还缺什么、外部项目到底该借哪一段，不该借哪一段”。

---

## 1.1 三个项目的角色定位

| 项目 | 强项 | 不足 | 对 AITeachMe 的价值 |
| --- | --- | --- | --- |
| `gpt-researcher` | 深度研究范式、retriever 生态、压缩与 fallback | 教育语义弱，产物更像研究报告 | 提供 research 方法论和工具组织纪律 |
| `DeepTutor` | 教学产品形态、guide/interactive/media pipeline、上下文管理 | runtime 偏重，不适合整套照搬 | 提供课程化产物、交互页与媒体 sidecar 思路 |
| AITeachMe | 五大引擎、LangGraph/LangSmith、前后端一体、学习闭环方向明确 | 跨引擎协同与课程产品深度仍在补强 | 把研究能力、教学能力和用户长期学习闭环整合成统一系统 |

---

## 1.2 AITeachMe 当前已经固定下来的边界

### `shared/infra`

负责：

- LLM / tracing / storage / database / search / tools / skills 等基础设施
- 可跨引擎复用的底层 helper
- 通用 traced execution helper

不再负责：

- DocGen 业务专属 runtime
- workflow graph 编排
- 另一套业务 prompt builder 体系

### `teaching`

负责：

- 教学语义
- 文档脚手架
- 教学表达块
- teaching-owned 原子工具

不再负责：

- 第二套工具注册系统
- 第二套 runtime 编排层

### `workflows`

负责：

- graph / state / router
- workflow-local runtime
- workflow-local prompt assembly
- workflow tracing 主入口

这三层边界现在已经不是“建议”，而是当前代码的事实基础。

---

## 1.3 已经做对、不应该再推翻的部分

- 五大引擎主架构成立，不需要为了参考项目重拆总骨架。
- `digest/unified` 已经把 unified/docgen/kg/curriculum 的责任拆清。
- DocGen 已经是稳定的多节点 pipeline，而不是单 prompt 大函数。
- `teaching/documents` 已经具备教学脚手架，不是空壳目录。
- LangSmith 已经具备 workflow -> node -> substep -> prompt/retriever/llm 的统一观测面。

结论：

- 不要把 `DeepTutor` 的 capability runtime 搬进 AITeachMe。
- 不要把 `gpt-researcher` 的 deep research 结构原样照抄成新的 graph。
- 不要让 `teaching` 长成第二套 infra。

---

## 1.4 当前真正还缺的，不再是“有没有”，而是“做得够不够深”

### 差距 1：`retrieval_profile` 已进执行链，但学科化调权和缓存还不够成熟

现在的真实情况是：

- planner / docgen state 已有 `course_type` 与 `retrieval_profile`
- `DocGenChapterContextRuntime` 已真实把 profile 传入 retriever 工厂
- trace 和 lane summary 已区分 `requested_profile / applied_profile`
- 章节 research 已输出 `source_class_breakdown / research_rounds / coverage_score / gaps_remaining`

所以当前差距已经不是“profile 没打通”，而是：

- profile 粒度还不够学科化
- source class 权重仍偏通用
- retrieval / reader / compression 结果还没有系统化缓存策略

### 差距 2：research 已是 micro-loop，但覆盖评估和停机条件还可以更稳

当前 DocGen chapter research 已有：

- seed query + sub query planning
- per-round retrieve / curate / compress
- gap query enqueue
- coverage score / diminishing returns / round cap stop

后续主要还差：

- 更可靠的 coverage target 设计
- 更细的学科专用 gap 类型
- 更稳定的 round 收益评估
- 与 planner grounding 的前置检索更强联动

### 差距 3：课程产物已经像“讲义”，但还没完全像“会教的课程产品”

当前已经有：

- 模式感知的文档脚手架
- chapter title resolution
- practice layer
- 课程模式相关的结构块

真正还缺的是：

- 错因卡
- 公式解释卡 / 推导卡
- 变式题与迁移题
- 更清晰的章节质量契约
- 更强的章节后测与画像闭环接口

### 差距 4：asset sidecar 已经起步，但 richer media 仍明显偏轻

当前状态：

- Mermaid：已进入 sidecar 主线
- image：有最小可执行链，但仍偏占位式
- interactive HTML：已有最小模板链路
- animation：仍只是 contract / trace 预留位

这意味着下一步重点不是“从 0 到 1 建 sidecar”，而是“把 sidecar 做深、做稳、做出教育价值”。

### 差距 5：跨引擎协同还没有完成第二阶段

当前最明显的未闭环点：

- Interact 还没有完整复用 Digest 的 `selected_skillpacks` 与课程合同语义
- Examine 还没有更深共享 Digest 生成出的章节研究上下文和教学动作信息
- Profile 还没有把 Digest 课程产物、Examine 练习结果和 Interact 追问统一成更稳定的学习画像输入

---

## 1.5 现在真正该借什么

### 从 `gpt-researcher` 借

- query planning 与检索执行分离
- 深度研究的轻量补检索纪律
- 压缩快慢路径
- fallback 与多层模型路由的工程化约束

### 从 `DeepTutor` 借

- 课程产品形态
- 交互 HTML / rich media sidecar 的独立流水线思路
- pre-retrieval planning
- 长对话 / 长构建的上下文压缩与 budget 思路
- 知识点级 follow-up 与学习页面形态

### AITeachMe 自己必须坚持

- 五大引擎主架构不动
- `shared/infra / teaching / workflows` 三层边界不动
- Docs Lane 的升级优先在 Digest 内完成，不外溢重写其他引擎
- LangSmith 继续作为算法迭代的第一观测台

---

## 1.6 当前最值得投入的下一批工作

1. 继续做 retrieval 的学科化 profile、source class 调权和缓存。
2. 把 research micro-loop 的 coverage / stop 逻辑做得更稳定。
3. 把 richer teaching blocks、practice 结构和章节质量契约继续做深。
4. 把 interactive/image sidecar 从“最小可用”做成“真正有教学价值”。
5. 把 Digest 和 Interact / Examine / Profile 的关键合同进一步打通。

---

## 1.7 一句话结论

AITeachMe 当前不缺总骨架，真正缺的是：

- 把已有能力做深，而不是再发明一套新架构
- 把课程产物做强，而不是只把研究流程做长
- 把跨引擎合同打通，而不是让 Digest 一枝独秀