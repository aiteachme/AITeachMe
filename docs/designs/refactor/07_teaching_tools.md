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

---
