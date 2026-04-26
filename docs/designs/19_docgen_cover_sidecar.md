# 19. DocGen 封面 Sidecar

最后更新：2026-04-27

本文是 DocGen 封面能力的当前事实源。封面是可选增强资产，不是正文生成的成功条件。

## 1. 当前合同

- 开关：`docgen.generate_cover_image`
- 默认值：`False`
- 模型：走 `settings.models.image_generation`
- 运行方式：DocGen 主图中的 `generate_cover` best-effort 节点
- 失败语义：返回空封面并继续生成正文
- 形态：横向 banner，抽象、艺术化、风景化
- 禁止：文字、数字、公式、图表、UI、课本封面 mockup、教室道具

## 2. 主流程

```text
load_context / prepare_global_seed
  -> generate_cover
  -> merge_review / sync_locked_titles
  -> publish_document
```

`generate_cover` 会根据 subject、用户目标、confirmed plan、资料摘要和 intent profile 生成封面。它只写封面 state 和资产，不改正文结构；后续合成节点如果拿到封面，就把 Markdown 插到整本文档最顶部。

## 3. 代码入口

| 职责 | 文件 |
| --- | --- |
| 配置默认值 | `backend/app/shared/infra/settings/defaults.py` |
| 配置 schema | `backend/app/shared/infra/settings/settings.py` |
| 设置页目录 | `backend/app/workflows/support/system/catalog.py` |
| Graph 节点 | `backend/app/workflows/digest/docgen/nodes/generate_cover.py` |
| 图片生成与存储 | `backend/app/workflows/digest/docgen/lib/cover.py` |
| 文档合成 | `merge_review.py`、`sync_locked_titles.py`、`publish_document.py` |
| 前端渲染 | `MarkdownViewer.tsx`、`KnowledgeDocsPage.tsx` |
| 导入导出 | `workflows/support/export_import/exports.py`、`imports.py` |

## 4. 产物

稳定图片路径：

```text
users/<user>/subjects/<subject>/assets/docgen/cover.<ext>
```

构建元数据：

```text
knowledge_markdowns/_build/cover_artifact.json
```

文档 Markdown：

```md
![](../assets/docgen/cover.png)
```

导出 `.atmx` 时只打包当前稳定封面；导入时恢复到目标用户和目标 subject 的 `assets/docgen/` 下。

## 5. 文档顺序

发布后的整本文档前部固定为：

1. 封面图
2. `# 知识文档总览`
3. `## 目录`
4. 总览正文
5. 各章节
6. 参考资料

## 6. 当前取舍

- 不支持单次构建覆盖开关。
- 不开放自由 prompt。
- 不做封面版本管理。
- 生成成功后清理旧的 `docgen_cover_*` / `cover.*` 文件，只保留当前稳定封面。

后续如果要扩展，优先顺序是：单次构建覆盖字段、封面风格枚举、manifest 封面元数据、统一资产 sidecar 编排。
