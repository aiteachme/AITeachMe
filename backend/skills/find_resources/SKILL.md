---
name: find_resources
description: 根据学习主题，自动搜索互联网上的免费学习资料并整理推荐
version: "1.0"
tags:
  - 教学
  - 检索
  - 资源推荐
prompt_scope:
  - digest.planner
  - digest.docgen.research
recommended_tool_tags:
  - retrieval
  - web_search
  - knowledge_lookup
defaults:
  difficulty: 入门
parameters:
  topic:
    type: string
    description: 学习主题（如"线性代数"、"Python基础"）
    required: true
  difficulty:
    type: string
    description: 难度级别（入门/进阶/高级）
    default: 入门
---

# 搜索学习资料

根据用户提供的学习主题，执行以下步骤：

## 执行流程

1. **构建搜索查询**：根据主题和难度级别，生成多个搜索查询
   - `"{topic} {difficulty} 教程 免费"`
   - `"site:github.com {topic} tutorial"`
   - `"{topic} 在线课程 推荐"`

2. **搜索互联网**：使用 `web_search` 工具执行每个查询

3. **整理推荐列表**：将搜索结果整理为结构化推荐，每条包含：
   - 资源标题
   - 链接
   - 简要描述
   - 推荐理由

4. **按质量排序**：优先推荐以下类型的资源
   - 知名教育平台（如 MIT OCW、Coursera 免费课）
   - GitHub 高星教程仓库
   - 官方文档和教程
   - 社区推荐的学习路径

## 注意事项

- 优先推荐中文资源，但不排斥优质英文资源
- 标注资源类型（视频/文章/互动教程/题库）
- 筛除付费内容，只推荐免费可用的资源
