---
name: explain_with_analogy
description: 用生动的类比和比喻解释难懂的学术概念，帮助学生建立直觉理解
version: "1.0"
tags:
  - 教学
  - 解释
  - 类比
prompt_scope:
  - digest.docgen.writer
  - interact
recommended_tool_tags:
  - teaching
  - explain
defaults:
  student_level: 初学
parameters:
  concept:
    type: string
    description: 需要用类比解释的概念
    required: true
  student_level:
    type: string
    description: 学生水平（初学/有基础/进阶）
    default: 初学
---

# 类比教学

用日常生活中的类比和比喻，让抽象概念变得直觉好懂。

## 执行流程

1. **理解概念本质**：先用一句话概括这个概念的核心要义
2. **构思类比**：找到一个日常生活中的场景或事物，与这个概念有相似的结构
3. **展开类比**：详细对照类比中的每个元素和概念中的对应关系
4. **指出类比边界**：说明类比在哪里不再适用，避免误导
5. **回归严谨**：最后用一段正式但通俗的语言总结概念

## 类比原则

- 类比应与学生的日常经验相关
- 优先使用**中国学生熟悉的**场景（食堂排队、外卖配送、微信群等）
- 类比粒度适配学生水平
- 一个概念可以提供 2-3 个不同角度的类比
- 始终标注"这只是类比，严格来说..."
