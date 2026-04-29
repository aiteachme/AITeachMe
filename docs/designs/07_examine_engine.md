# 07. Examine 诊断引擎

最后更新：2026-04-27

本文是 Examine 的跨模块事实页。目录结构和入口以 `backend/app/workflows/examine/README.md` 为准。

## 当前职责

Examine 负责题目生成、试卷构建、提交判卷、错因反馈和与 Profile 的掌握度更新衔接。

它不负责：

- 构建知识图谱。
- 维护长期画像算法本身。
- 直接生成知识文档。

## 代码入口

| 职责 | 文件 |
| --- | --- |
| API | `backend/app/api/exams.py` |
| 稳定导入面 | `backend/app/workflows/examine/__init__.py` |
| 题目构建链路 | `backend/app/workflows/examine/question_build/` |
| 判卷链路 | `backend/app/workflows/examine/exam_grade/` |
| Profile 衔接 | `backend/app/workflows/profile/` |

稳定入口：

```python
from app.workflows.examine import (
    build_exam_grade_graph,
    build_question_build_graph,
    run_question_build_workflow,
)
```

## 公开 API 形态

当前 `/api/v1/courses/{course}/exams` 提供：

- 生成试卷。
- 查询试卷历史。
- 查询题型和题库模板。
- 查询生成状态 SSE。
- 获取试卷详情。
- 删除试卷。
- 提交答案并触发掌握度更新。
- 从已评分试卷生成学习指南。

## 主流程

```text
KnowledgeUnit / weak states / review tasks
  -> question_build
  -> exam_paper / exam_paper_item
  -> exam_grade
  -> update_mastery_from_exam
  -> schedule_reviews
```

题目生成和判卷可以调用 LLM；客观题仍以标准答案和规则校验为主，LLM 主要用于个性化反馈和主观题判分。

## 约束

- 对外不再使用旧 `exam / question / mistake / user_profile` 表作为真相源。
- 知识点范围以 `knowledge_unit` 为主。
- 掌握度写入交给 Profile，Examine 只负责在判卷后触发。
- 试卷历史归因应基于组卷时保存的知识点映射，不被后续图谱变化悄悄改写。
