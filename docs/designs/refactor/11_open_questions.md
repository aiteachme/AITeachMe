## 十一、开放问题（需要确认）

> **最后更新**：2026-04-08 — 标记已解决的问题，新增实现过程中发现的新问题

> [!IMPORTANT]
> 以下问题将直接影响代码实现路径，请逐条确认：

### 11.1 模型与 API 相关

1. **文生图模型选择** — ⬜ 待确认
   - 通义万相 (Wanxiang) 还是 Qwen-VL？或者 Gemini Flash Image / DALL-E？
   - 当前状态：ImageGenerator 框架已就绪（占位符处理），实际生成 API 待接入
   - 建议：MVP 阶段用通义万相（DashScope 生态内，API 统一），V2 再考虑 Gemini / DALL-E

2. **Strategic LLM 选择** — ✅ 已通过配置解决
   - `acompletion_with_fallback()` 支持 `tier` 参数，默认模型通过 `model_overrides` 配置
   - 当前默认：Strategic → REASONING TaskType 对应的模型

3. **Bing Search API Key** — ✅ 已解决
   - Bing 检索器已实现（`search/retrievers/bing.py`），通过 `.env` 配置 API Key
   - 博查搜索也已实现（`search/retrievers/bocha.py`）作为备选

### 11.2 文档模式相关

4. **速成课章节数是否可配置** — ⬜ 待确认
   - 当前 Planner Prompt 中约束章节数，但未硬性锁死 4 节
   - 建议：MVP 通过 Prompt 约束为 4 节，V2 开放配置

5. **系统课字数目标** — ⬜ 待确认
   - 当前通过 `writing_instructions` 控制，但实际生成字数需要端到端验证
   - 需要：跑一次完整的系统课生成，验证字数是否达到 10000+

6. **语言风格是否暴露给用户** — ⬜ 待确认
   - `tone` 参数已在 `DocGenState` 和 `SkillContext` 中支持
   - 建议：MVP 速成课默认 casual，系统课默认 professional。V2 前端开放选择

7. **速成课/系统课格式模板** — 🟡 部分实现
   - `archetype_prompts.py` 已实现按章节类型选择 Prompt（概念构建/方法求解/题型/复习）
   - 但尚未严格区分速成课 vs 系统课的固定章节结构（05 文档中定义的）
   - 需要：在 `planner_prompts.py` 中强化速成课 4 节固定结构约束

### 11.3 检索与资源相关

8. **本地教育语料库的初始范围** — ⬜ 待实现（Phase 4）
   - 建议不变：先覆盖高等数学（微积分、线性代数、概率论）

9. **蜂考等商业素材的合规处理** — ⬜ 待法务确认
   - 建议不变：① 不存储原文 ② 用 AI 重新组织 ③ 标注"参考来源"

10. **检索结果缓存** — ⬜ 待实现
    - 当前无缓存，每次搜索都是实时请求
    - 建议：内存 dict 缓存，TTL 1 小时（见 09 文档 9.9 节）

### 11.4 前端与交互相关

11. **交互式 HTML** — ⬜ V2 预留
    - 当前无 `[INTERACTIVE:]` 占位符处理
    - 建议不变：MVP 不支持

12. **文档导出格式** — ⬜ 待确认
    - 建议不变：MVP 只支持前端渲染 + Markdown 下载

13. **文档版本管理** — ⬜ 待确认
    - 当前 `finalize_node` 每次生成新 doc_ids，不覆盖旧版本
    - 需要：前端展示历史版本切换 UI

### 11.5 其他框架调研（不变）

14. **其他 Deep Research 框架**：
    - [STORM (Stanford)](https://github.com/stanford-oval/storm) — 学术论文级别的研究报告生成
    - [Tavily Research](https://tavily.com) — 专注搜索质量的 API
    - [Perplexity-style](https://github.com/rashadphz/farfalle) — 开源 Perplexity 克隆
    - 建议：当前 gpt-researcher 的 Plan-Execute 范式已经足够，其他框架可作为 V2 参考

15. **教育领域专属工具/API**：
    - [Wolfram Alpha API](https://products.wolframalpha.com/api/) — 数学计算验证
    - [Mathpix](https://mathpix.com/) — OCR 识别手写公式
    - [Khan Academy API](https://www.khanacademy.org/) — 教育内容
    - 建议：Wolfram Alpha 可在 V2 集成

### 11.6 新增问题（实现过程中发现）

16. **Planner 与 DocGen 的解耦边界** — 🟡 需要明确
    - 当前 Planner 是独立 workflow（`planner/graph.py`），其输出通过 `confirmed_plan` 传入 DocGen
    - 原设计中 `edu_planner` 是 DocGen graph 内部节点，实际实现已分离
    - 问题：Planner 的 Prompt 质量直接决定 DocGen 输出质量，但两者在不同 graph 中，调试时需要跨 graph 追踪
    - 建议：在 LangSmith 中通过 `planner_session_id` + `confirmed_plan_id` 关联两个 graph 的 trace

17. **ResearchConductor 的 purify 步骤是否必要** — 🟡 需要数据验证
    - 当前 ResearchConductor 在 ContextManager 压缩后还有一步 LLM purify
    - 这增加了一次 Smart LLM 调用（成本 + 延迟）
    - 需要：对比有/无 purify 的文档质量差异，决定是否保留或改为可选

18. **archetype_prompts 的章节类型匹配准确度** — 🟡 需要验证
    - `get_writer_prompt()` 根据章节类型选择不同的 Prompt 模板
    - 但章节类型由 Planner 输出决定，如果 Planner 输出的类型标签不准确，会导致 Prompt 不匹配
    - 需要：验证 Planner 输出的章节类型与 archetype_prompts 的匹配率

19. **fan-out 并发度与 API rate limit 的平衡** — ⬜ 待调优
    - 当前 `targeted_research` 和 `pedagogy_craft` 都使用 Send() fan-out
    - 如果章节数较多（系统课 8-10 章），同时发起的 LLM 调用 + 搜索请求可能触发 rate limit
    - 需要：通过 `docgen_max_parallel_chapters` 配置控制并发度，并在 LangSmith 中监控 rate limit 错误

20. **前端 Mermaid / KaTeX 渲染兼容性** — ⬜ 待验证
    - 后端生成的 Mermaid 语法和 LaTeX 公式需要前端正确渲染
    - 需要：验证前端 Mermaid.js 和 KaTeX 组件是否已集成，以及复杂公式的渲染效果

---
