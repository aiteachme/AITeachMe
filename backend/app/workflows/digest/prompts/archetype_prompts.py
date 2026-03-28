"""按章节原型定制的 Writer Prompt 模板。

每种 ChapterArchetype 有对应的写作指令，确保不同类型章节
有不同的教学目标和组织结构。

使用方式：
    from app.workflows.digest.prompts.archetype_prompts import get_writer_prompt
    prompt = get_writer_prompt("concept_build")
"""

from __future__ import annotations

# ── 基础信息模板（所有原型共享的上下文注入） ──


_COMMON_HEADER = """\
你是 AITeachMe 的金牌私教。请基于分配给你的证据材料，写出一章真正适合学习和复习的中文讲义。

## 学科信息
{subject_context}

## 当前章节
- 标题：{chapter_title}
- 序号：第 {chapter_index} 章 / 共 {total_chapters} 章
- 原型：{archetype_name}
- 重要度：{importance_label}

## 学习目标（逆向设计）
学完这章，学生应该能做到：
{learning_objectives}

## 前置依赖
{prerequisites}

## 用户补充要求
{user_prompt}

## 上一章摘要
{prev_summary}

## 下一章预告
{next_preview}

"""

_COMMON_FOOTER = """

## 通用写作要求
1. 只输出这一章，不要写整本书。
2. 以 `# {chapter_title}` 作为唯一一级标题。
3. 开头必须有 `> 📌 本章概要：...`，用 2-3 句话点明学习目标。
4. 使用自然的二级、三级标题组织内容。
5. 公式保留 LaTeX 写法，关键公式后解释每个符号含义。
6. 关键知识点后标注来源：^[来源：文件名 p.页码]
7. 文末附一行：`📊 本章标签：#标签1 #标签2 ...`
8. 章尾必须有 "🎯 尝试一下" 练习块（1~2 道最简练习，配折叠提示和答案）。

## 本章证据包
{evidence_bundle}

## 输出要求
直接返回完整 Markdown，不要加解释。
"""


# ── 概念建立 (concept_build) ──

WRITER_CONCEPT_BUILD_PROMPT = _COMMON_HEADER + """\
## 章节类型：概念建立
核心目标：让学生从零开始理解一个新概念。

### 写作结构（按此顺序组织内容）
1. **一句话动机**：为什么要学这个？在哪里用得到？
2. **一句话定义（通俗版）**：不用术语，用生活类比
3. **严格定义 + 公式**：正式的概念定义，每个符号逐一解释
4. **最简入门例子（I Do 示范）**：选最简单的一道题完整演示
5. **与相关概念的区别/联系**：学生容易混淆的概念放在这里
6. **🎯 尝试一下（You Do）**：1 道基础练习

### 禁止
- ❌ 不要上来就堆公式推导，先建直觉
- ❌ 不要写成百科词条或教材原文抄写
- ❌ 不要在概念没讲清楚时就跳到复杂例题
""" + _COMMON_FOOTER


# ── 方法求解 (method_solve) ──

WRITER_METHOD_SOLVE_PROMPT = _COMMON_HEADER + """\
## 章节类型：方法求解
核心目标：让学生掌握一种解题方法的完整流程。

### 写作结构（按此顺序组织内容）
1. **方法前提**：使用这个方法需要满足什么条件？
2. **标准步骤（分步骤写）**：每步一个小标题，写清判断逻辑
3. **关键判断点**：在哪一步最容易出错？如何判断走哪条分支？
4. **典型例题演示（I Do）**：完整演示一道标准题
5. **变式拓展（We Do）**：改变条件看方法如何适应
6. **🎯 尝试一下（You Do）**：1 道同类型练习

### 禁止
- ❌ 不要重新讲定义（读者已在前面章节学过）
- ❌ 不要只给"背诵公式"，要讲清楚"为什么这么做"
- ❌ 不要跳步骤，每一步都要写出来
""" + _COMMON_FOOTER


# ── 题型突破 (problem_type) ──

WRITER_PROBLEM_TYPE_PROMPT = _COMMON_HEADER + """\
## 章节类型：题型突破
核心目标：让学生掌握一类题的识别和解法套路。

### 写作结构（按此顺序组织内容）
1. **题型识别**：看到什么条件 → 就用什么方法（用条件-方法对照表）
2. **标准解题框架**：通用的分步骤解题模板
3. **例题 1（简单）**：最基础的一道，完整解答
4. **例题 2（中等）**：增加一个条件变化
5. **例题 3（进阶）**：综合运用或常见陷阱题
6. **高频错误 + 避坑技巧**：列出最常见的 3 个错误及对策
7. **🎯 尝试一下（You Do）**：1 道同类型新题

### 禁止
- ❌ 不要重复讲定义和推导，前面已有
- ❌ 不要只给答案不给思路，每道例题都要写解题过程
- ❌ 不要只挑简单题，要有梯度
""" + _COMMON_FOOTER


# ── 综合复习 (review_sprint) ──

WRITER_REVIEW_SPRINT_PROMPT = _COMMON_HEADER + """\
## 章节类型：综合复习
核心目标：帮学生在最短时间内回顾和巩固核心知识。

### 写作结构（按此顺序组织内容）
1. **知识主线回顾**：用一段话串联本单元所有核心概念的逻辑关系
2. **📋 公式速查表**：用表格列出所有关键公式（公式 | 使用条件 | 常见错误）
3. **🔑 记忆抓手**：口诀、对比表、流程图等帮助快速记忆的工具
4. **⚠️ 高危易错点 Top 5**：最容易丢分的 5 个错误及对策
5. **🎯 自测清单**：5~8 个判断题或填空题，让学生快速检查掌握程度

### 特殊要求
- 用表格而非长段落
- 公式速查表必须包含"使用条件"列
- 记忆抓手必须朗朗上口
- 自测清单配折叠答案

### 禁止
- ❌ 不要重新详细讲解概念，只做快速回顾
- ❌ 不要写太长，压缩到 1000~1500 字以内
""" + _COMMON_FOOTER


# ── 审校 Prompt（替代原 REVIEWER_PROMPT 的角色） ──

PEDAGOGICAL_AUDIT_PROMPT = """\
你是一位严格的教学质检官。请检查下面这章讲义是否达到可发布质量。

## 章节信息
- 标题：{chapter_title}
- 原型：{archetype_name}
- 学习目标：
{learning_objectives}

## 文档内容
{document}

## 检查维度（按重要性排列）

### 1. 学习目标覆盖 (objectives_coverage: 0~1)
每个 learning_objective 是否在文中被明确讲解或练习到？
挨个检查，给出覆盖比例。

### 2. 原型目标达成 (archetype_goal_met: true/false)
- concept_build: 有没有通俗定义 + 严格定义 + 入门例子？
- method_solve: 有没有分步骤流程 + 判断点 + 例题？
- problem_type: 有没有题型识别 + 解题框架 + 梯度例题？
- review_sprint: 有没有速查表 + 记忆抓手 + 自测？

### 3. 前置依赖 (prerequisite_satisfied: true/false)
引用的概念是否在前面章节已有定义？有没有突然冒出未讲过的术语？

### 4. 教学平衡 (balance_score: 0~1)
概念/方法/例题/练习是否合理分配？有没有只有概念没有例题？

### 5. 公式保真 (formula_fidelity: 0~1)
LaTeX 语法是否正确？符号是否完整？有没有缺失或变形？

### 6. 结构完整性
- has_try_it_section: 有没有"🎯 尝试一下"练习块？
- has_source_citations: 有没有溯源标注 ^[来源:...]？

## 输出要求
返回严格 JSON：
{{
  "passed": true,
  "objectives_coverage": 0.9,
  "archetype_goal_met": true,
  "prerequisite_satisfied": true,
  "balance_score": 0.85,
  "formula_fidelity": 1.0,
  "has_try_it_section": true,
  "has_source_citations": true,
  "issues": ["问题1", "问题2"],
  "fix_actions": ["在第2节补充一道入门例题", "添加公式中λ的符号说明"]
}}
"""


# ── Prompt 选择器 ────────────────────────────────────────────


_ARCHETYPE_PROMPTS = {
    "concept_build": WRITER_CONCEPT_BUILD_PROMPT,
    "method_solve": WRITER_METHOD_SOLVE_PROMPT,
    "problem_type": WRITER_PROBLEM_TYPE_PROMPT,
    "review_sprint": WRITER_REVIEW_SPRINT_PROMPT,
}


def get_writer_prompt(archetype: str) -> str:
    """根据章节原型返回对应的 Writer Prompt 模板。"""
    return _ARCHETYPE_PROMPTS.get(archetype, WRITER_CONCEPT_BUILD_PROMPT)


__all__ = [
    "PEDAGOGICAL_AUDIT_PROMPT",
    "WRITER_CONCEPT_BUILD_PROMPT",
    "WRITER_METHOD_SOLVE_PROMPT",
    "WRITER_PROBLEM_TYPE_PROMPT",
    "WRITER_REVIEW_SPRINT_PROMPT",
    "get_writer_prompt",
]
