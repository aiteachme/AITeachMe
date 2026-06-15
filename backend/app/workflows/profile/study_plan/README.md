# Profile Study Plan 链路

最后更新：2026-06-15

`profile/study_plan/` 根据当前画像生成下一步学习建议。它不是 Digest Planner。

```text
输入: course_profile + user_profile
输出: review / practice / reflect 三步计划
```

## 主流程

```text
load_profile_context
  -> build_study_plan
```

## 1. `load_profile_context`

输入：

```text
course_id
user_id
```

动作：

```text
现场构建 course_profile。
现场构建 user_profile。
不写数据库。
```

输出：

```text
course_profile
user_profile
```

读取/生成的关键字段：

```text
course_profile.due_review_count
course_profile.weak_knowledge_unit_count
course_profile.recommended_exam_mode
course_profile.recommended_question_count
course_profile.difficulty_focus
course_profile.recommended_question_types
user_profile.explanation_style
```

## 2. `build_study_plan`

输入：

```text
course_profile
user_profile
```

动作：

```text
确定性生成 3 个学习动作。
不调 LLM。
```

输出：

```text
study_plan[]
```

`study_plan[]`：

```text
key
title
detail
action
priority
source
```

当前三步：

```text
1. review
   来源: review_state
   目标: 先处理到期复习或薄弱知识点

2. practice
   来源: course_profile
   目标: 按推荐题型、题量、难度做定向练习

3. reflect
   来源: user_profile
   目标: 按解释风格复盘错题和迁移规则
```

## 边界

```text
不写 DB。
不调 LLM。
不生成 Digest confirmed_plan。
不替代 Examine 出题。
只给下一步学习动作建议。
```

## 修改检查

- 改推荐动作时同步 Profile 页面展示。
- 新增 action/source 要确认前端能识别。
- 需要持久化计划时不要直接塞进当前只读链路。
