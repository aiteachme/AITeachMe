# DocGen 最新重构落地说明

最后更新：2026-04-17

状态：已按最新方案重构核心 graph。

## 总判断

DocGen 已切换为新流程：

```text
load_context
  -> prepare_parallel_inputs
       ├─ enhance_plan_outline
       ├─ infer_docgen_intent
       └─ summarize_files
  -> confirm_and_dispatch
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> merge_review
  -> publish_document
```

Planner 仍然是用户确认计划的唯一来源。DocGen 的计划大纲增强只做执行级细化，不默认新增、删除、重排章节。

## 已删除的旧顶层节点

旧链路不再作为兼容目标：

- `research_chapters_node.py`
- `merge_research_node.py`
- `finalize_titles_node.py`
- `write_chapters_node.py`
- `merge_drafts_node.py`
- `enrich_assets_node.py`
- `append_practice_node.py`

底层可复用能力仍保留，例如：

- `lib/chapter_context.py`
- `lib/writer.py`
- `lib/assets.py`
- `lib/publish.py`

## 新增核心合同

核心模型集中在 `lib/models.py`：

- `DocGenContext`
- `DocGenIntentProfile`
- `FileMaterialSummary`
- `EnhancedChapterOutline`
- `ChapterGenerationPlan`
- `ChapterGenerationTask`
- `ChapterResearchTrace`
- `EvidenceLedger`
- `ChapterDraft`
- `EnhancedChapterDraft`
- `AssetManifest`
- `PracticeManifest`
- `MergeReviewReport`

## 新节点职责

| 节点 | 职责 |
| --- | --- |
| `load_context` | 读取 confirmed plan、shared inputs、文档上下文，生成 `DocGenContext` |
| `prepare_parallel_inputs` | 并行执行大纲增强、写作意图识别、文件摘要 |
| `confirm_and_dispatch` | 合并 0A/0B/0C，产出 `ChapterGenerationPlan` 和 `ChapterGenerationTask[]` |
| `generate_chapters` | 每章并行检索、压缩、证据抽取、正文生成、critic/rewrite |
| `enhance_chapters` | fan-in 后内部并发处理章节增强、资产、自检题、公式清洗 |
| `merge_review` | 合并章节并生成整本级 review report |
| `publish_document` | 发布 Markdown、DB 记录和结构化 DocGen manifest |

## 发布产物

DocGen 现在除 Markdown 外还写结构化 manifest：

```text
knowledge_markdowns/_build/docgen_manifest.json
knowledge_markdowns/docgen_manifest.json
knowledge_markdowns/versions/vXXXX/docgen_manifest.json
```

manifest 包含：

- `docgen_context`
- `intent_profile`
- `file_summaries`
- `chapter_generation_plan`
- `enhanced_chapter_drafts`
- `research_traces`
- `evidence_ledgers`
- `asset_manifest`
- `practice_manifest`
- `merge_review_report`

## 已验证

- `python -m compileall backend/app/workflows/digest/docgen backend/app/utils/docgen_store.py backend/app/workflows/digest/common/exports.py`
- `get_langgraph_dev_docgen_graph().compile()`
- mock 版 DocGen graph：2 个章节从生成、增强、merge review 到 publish 全流程通过
- `pytest backend/tests -q`

## 后续优先级

1. 为新模型补独立单元测试。
2. 为 `prepare_parallel_inputs` 的 0A/0B/0C fallback 补节点测试。
3. 用真实小资料跑一次 sprint/systematic 构建，观察 LLM 成本和章节质量。
4. 后续如果 `examine/question_build` 真实落地，再把 `PracticeManifest` 接到 Examine。
