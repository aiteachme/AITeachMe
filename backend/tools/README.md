# 工具定义目录

> 在此定义 LLM 可用的工具预设。每个 `.yaml` 文件描述一个工具的元信息。
> Python 实现在 `core/tools/builtin/` 目录下。

## 结构

```
backend/tools/
├── README.md           ← 本文件
├── web_search.yaml     ← 工具定义（元信息）
├── search_kb.yaml
├── remember_info.yaml
└── ...
```

## 工具定义格式

```yaml
name: web_search
description: 搜索互联网获取最新相关信息
version: "1.0"
category: 检索
enabled: true
parameters:
  query:
    type: string
    description: 搜索查询
    required: true
  top_k:
    type: integer
    description: 返回结果数量
    default: 5
```

## 与 Skill 的区别

- **Tool**：原子操作，一个函数调用即完成（如"搜索"）
- **Skill**：组合拳，可能调用多个 Tool + LLM 推理（如"搜索 → 整理 → 推荐"）
