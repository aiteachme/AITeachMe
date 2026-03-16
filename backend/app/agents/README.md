# Agents 模块

五大 AI 引擎的核心实现，每个子目录对应一个引擎。

## 目录结构

```
agents/
├── ingest/      # 摄入解析引擎
├── digest/      # 消化索引引擎
├── interact/    # 交互辅导引擎
├── examine/     # 测验判卷引擎
└── profile/     # 学习画像引擎
```

## ingest — 摄入解析

将用户上传的多格式文档（PDF、DOCX、PPTX、图片）解析为结构化 Markdown。

| 文件 | 职责 |
|------|------|
| `orchestrator.py` | 按文件扩展名分发到对应解析器，输出规范化 Markdown |
| `parsers.py` | 各格式解析器实现（MarkItDown / pymupdf4llm / LLM 视觉识别） |
| `prompts/` | 图片解析等场景的 LLM 提示词 |

## digest — 消化索引

将 Markdown 加工为可检索的知识单元，构建向量索引。

| 文件 | 职责 |
|------|------|
| `cleaner.py` | Markdown 清洗与格式规范化 |
| `outliner.py` | 提取文档大纲 / 知识结构 |
| `chunker.py` | 文本分块（用于向量化） |
| `embedder.py` | 调用 Embedding 模型生成向量 |
| `workflow.py` | LangGraph 状态机，编排 clean → outline → chunk → embed 流程 |
| `prompts/` | 各步骤的 LLM 提示词 |

## interact — 交互辅导

基于 RAG 的苏格拉底式教学对话引擎。

| 文件 | 职责 |
|------|------|
| `retriever.py` | 向量检索，召回相关知识块 |
| `context_builder.py` | 组装检索结果为 LLM 上下文 |
| `streamer.py` | SSE 流式输出对话响应 |
| `prompts/` | 对话系统提示词 |

## examine — 测验判卷

智能出题与自动判分。

| 文件 | 职责 |
|------|------|
| `generator.py` | 根据知识内容生成试题 |
| `grader.py` | 对用户答案进行自动判分与反馈 |
| `prompts/` | 出题和判分的 LLM 提示词 |

## profile — 学习画像

追踪学习进度，识别薄弱知识点。

| 文件 | 职责 |
|------|------|
| `reporter.py` | 汇总学习数据，生成掌握度报告 |
| `prompts/` | 画像分析的 LLM 提示词 |

## 通用约定

- 每个引擎目录下都有 `prompts/` 子目录，集中管理该引擎的 LLM 提示词
- 引擎之间不直接互调，统一通过 `services/` 层编排
- 所有异步函数优先使用 `async def`
