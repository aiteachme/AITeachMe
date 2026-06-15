# Courses Support

最后更新：2026-06-15

职责：处理课程注册、课程列表、课程详情、删除预览、级联删除、课程图标和学习上下文。

```text
输入: course request + user_id
输出: Course response / deletion preview / learning context
```

## 文件

```text
catalog.py            # 创建、列表、详情、更新
deletion.py           # 删除预览和删除执行
icons.py              # 课程图标生成/更新
learning_context.py   # 课程学习上下文
lib/deletion.py       # 删除内部实现
lib/model_policy.py   # 图标/上下文等模型策略
```

## 1. 课程目录

输入：`course_id`, `user_id`, 课程创建/更新字段

动作：创建、读取、更新课程，并校验归属。

输出：

```text
Course
Course response
```

## 2. 删除预览

输入：`course_id`, `user_id`

动作：统计删除会影响的文件、文档、考试、聊天、画像和运行时产物。

输出：删除预览 payload。

## 3. 删除执行

输入：`course_id`, `user_id`

动作：删除课程相关数据库记录和文件产物。

输出：删除结果。

## 4. 课程图标和学习上下文

输入：课程名称、课程说明、用户意图、已有资料摘要。

动作：生成课程图标或课程学习上下文。

输出：

```text
icon payload
learning context text
```

## 边界

`courses` 不解析文件；文件生命周期在 `ingest/intake`。

`courses` 不生成知识文档；文档生成在 `digest/docgen`。

`courses` 是 support 用例，不是 LangGraph lane。
