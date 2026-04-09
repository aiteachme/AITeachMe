## 七、教育工具集成与 Teaching Skills

### 7.1 可集成的教育领域工具调研

| 工具/服务 | 用途 | 集成方式 | 优先级 |
|:---|:---|:---|:---|
| **Wolfram Alpha API** | 数学公式验证、符号计算、函数图像 | REST API → Action | P2 |
| **Manim / 3Blue1Brown** | 数学动画生成（如偏导数几何意义动画） | Python 库 → Skill | P3（V2） |
| **Desmos API** | 交互式函数图像嵌入 | iframe 嵌入 → InteractiveBuilder | P2 |
| **GeoGebra** | 几何/代数交互演示 | iframe 嵌入 → InteractiveBuilder | P3（V2） |
| **KaTeX / MathJax** | LaTeX 公式前端渲染 | 前端集成（已有基础） | P0 |
| **Mermaid.js** | 思维导图/流程图前端渲染 | 前端集成 | P1 |
| **Excalidraw** | 手绘风格图表 | 前端集成（可选） | P3 |
| **Anki Connect** | 导出为 Anki 闪卡 | REST API → Action | P3 |

### 7.2 Skill 类型对照表

两种 Skill 实现模式的适用场景：

| 特性 | `@skill` 装饰器（轻量） | `BaseSkill` 类（重量级） |
|:---|:---|:---|
| **状态** | 无状态函数 | 有状态类（持有 SkillContext） |
| **适用场景** | 单步操作 | 多步编排 |
| **LLM 调用** | 被 LLM tool_call 调用 | 被 LangGraph 节点直接调用 |
| **LangSmith 追踪** | 通过 ToolRegistry 自动追踪 | 通过 `BaseSkill.run()` 包装追踪 |
| **示例** | `solve_step_by_step`, `explain_formula` | `ResearchConductor`, `ImageGenerator` |

### 7.3 Teaching Skills 扩展

在 `shared/infra/skills/` 中预留教育专属 Skill 接口：

```python
# ── @skill 装饰器：轻量级，被 LLM tool_call 调用 ──

@skill("solve_step_by_step", "对数学题进行分步求解并展示过程")
async def solve_step_by_step(problem: str, subject: str = "math") -> str:
    """调用 Strategic LLM 进行分步求解。"""
    ...

@skill("generate_similar_problems", "根据一道题生成相似变型题")
async def generate_similar_problems(problem: str, count: int = 3) -> str:
    """调用 Smart LLM 生成变型题。"""
    ...

@skill("explain_formula", "用大白话解释一个数学公式")
async def explain_formula(formula: str, level: str = "beginner") -> str:
    """调用 Fast LLM 生成公式的通俗解释。"""
    ...

@skill("compare_concepts", "对比两个易混淆概念")
async def compare_concepts(concept_a: str, concept_b: str) -> str:
    """生成对比表格。"""
    ...
```

这些 Skill 可以在 `pedagogy_craft` 节点的写作过程中被 LLM 通过 tool_call 调用，也可以在 `enrich_document` 阶段独立调用。

### 7.4 真正需要补齐的 Teaching Tool 分层（新增）

如果目标是“工具覆盖面要比 GPT-Researcher 更多更好”，教学工具不能只停留在 4 个示例函数，至少应分成下面 5 组：

| 分组 | 目标 | 示例工具 |
|:---|:---|:---|
| 概念教学 | 讲清楚“是什么” | `explain_formula` / `compare_concepts` / `build_glossary_section` |
| 方法教学 | 讲清楚“怎么做” | `solve_step_by_step` / `method_selector` / `proof_outline_builder` |
| 练习生成 | 讲清楚“怎么练” | `generate_similar_problems` / `difficulty_ladder_builder` / `distractor_builder` |
| 纠错诊断 | 讲清楚“哪里容易错” | `misconception_detector` / `error_pattern_explainer` |
| 记忆迁移 | 讲清楚“怎么记、怎么迁移” | `memory_hooks_builder` / `analogy_builder` / `transfer_question_builder` |

#### 7.4.1 推荐优先补齐的 Teaching Tools

**P1：必须优先做**

- `build_misconception_section`
  - 生成“易错点 / 常见误区”
- `build_formula_walkthrough_section`
  - 对关键公式做逐项解释
- `build_example_variations_section`
  - 同一例题的 2-3 个变式
- `difficulty_ladder_builder`
  - 基础 -> 中档 -> 综合 的题目梯度
- `memory_hooks_builder`
  - 秒杀口诀 / 类比 / 记忆钩子

**P2：对理工科非常有价值**

- `proof_outline_builder`
  - 证明题思路骨架
- `graph_scene_builder`
  - 函数图像/几何场景说明
- `unit_conversion_checker`
  - 物理/工程单位一致性检查
- `symbolic_math_checker`
  - 接 Wolfram / SymPy 的数学验证工具

**P3：系统课质量增强**

- `dependency_explainer`
  - 解释知识前置依赖
- `concept_transfer_builder`
  - 构造跨章节迁移题
- `oral_quiz_builder`
  - 生成口头提问卡片
- `anki_export_builder`
  - 闪卡导出

### 7.5 一个关键判断：AITeachMe 不该只比它“工具更多”，而要比它“教学链更完整”（新增）

GPT-Researcher 的强项是：

- 找资料
- 读资料
- 写报告

AITeachMe 该强于它的地方是：

- 找资料
- 读资料
- 组织证据
- 写讲义
- 插图和交互演示
- 出题
- 诊断误区
- 量化学习状态

所以“工具更多更好”的真正定义应该是：

- 检索更广
- 读取更稳
- 证据更结构化
- 教学工具更深
- 富媒体更强
- 验收更可量化

而不是简单比较“总共有多少个 retriever”。

---
