---
name: review_mistakes
description: 汇总用户的错题记录，按知识点分类分析，并生成针对性复习建议
version: "1.0"
tags:
  - 教学
  - 诊断
  - 错题
prompt_scope:
  - examine
  - interact
recommended_tool_tags:
  - teaching
  - practice
defaults:
  days: 7
parameters:
  subject:
    type: string
    description: 学科标识
    required: true
  days:
    type: integer
    description: 回溯天数
    default: 7
---

# 错题复习

汇总近期错题，帮助学生精准复习薄弱点。

## 执行流程

1. **收集错题**：查询最近 {days} 天内，学科 {subject} 下的所有错题记录
2. **知识点归类**：将错题按知识点分组，统计每个知识点的错误频次
3. **分析错因**：对高频错误知识点，分析常见错因模式
4. **生成建议**：
   - 按优先级排列薄弱知识点
   - 为每个薄弱点推荐复习策略
   - 生成 3-5 道类似练习题供强化
5. **更新画像**：将分析结果记录到用户记忆中

## 输出格式

```
📊 错题分析报告
━━━━━━━━━━━━━━
🔴 高频薄弱: [知识点列表]
🟡 偶尔出错: [知识点列表]
🟢 已掌握:   [知识点列表]

📝 复习建议:
1. ...
2. ...

🎯 针对性练习:
1. ...
```
