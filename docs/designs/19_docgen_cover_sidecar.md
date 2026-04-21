# DocGen 封面 Sidecar 设计

最后更新：2026-04-21

## 1. 目标

为 `docgen` 增加一个可配置的封面能力：

- 由配置项控制是否生成
- 不阻塞正文主流程
- 封面图默认是横向、偏扁的 banner 形态
- 风格固定为抽象、艺术化、风景化
- 不允许出现任何文字、数字、公式、图表或 UI
- 最终始终放在整本文档最顶部

## 2. 当前配置

新增配置项：

- `docgen.generate_cover_image: bool`

默认值：

- `False`

配置归属：

- 属于 `project/system runtime settings`
- 本地模式可读可写
- 云端普通用户只读

## 3. 为什么不用主流程同步生成

如果把封面生成直接放进 `docgen` 主图里同步等待，会有两个问题：

1. 图片生成延迟波动比文本更大，容易拖慢整条链路
2. 图片失败不应该导致整本文档失败

所以当前实现采用 sidecar 方案：

- `run_docgen_background()` 在启动正文工作流前，额外创建一个封面生成任务
- 该任务独立运行，失败只记日志，不中断正文
- 后续 `merge_review` / `finalize_titles` / `publish_document` 会尽量读取 sidecar 产物

这意味着：

- 正文优先
- 封面是“尽量成功”的增强项
- 后面如果想升级成更强的资产编排，也不需要推翻主流程

## 4. 当前落点

### 后端

- 配置定义：
  - `backend/app/shared/infra/settings/settings.py`
  - `backend/app/shared/infra/settings/defaults.py`

- 封面 sidecar：
  - `backend/app/workflows/digest/docgen/lib/cover.py`

- 工作流触发：
  - `backend/app/workflows/digest/docgen/lib/build_lifecycle.py`

- 文档合成：
  - `backend/app/workflows/digest/docgen/lib/publish.py`
  - `backend/app/workflows/digest/docgen/nodes/merge_review.py`
  - `backend/app/workflows/digest/docgen/nodes/finalize_titles.py`
  - `backend/app/workflows/digest/docgen/nodes/publish_document.py`

### 前端

- 设置页展示该开关：
  - `frontend/src/components/settings/SettingsPanel.tsx`

- 文档页支持受保护资源图片渲染，并对 `docgen` 封面做 banner 化展示：
  - `frontend/src/components/ui/MarkdownViewer.tsx`
  - `frontend/src/pages/KnowledgeDocsPage.tsx`

## 5. 提示词约束

封面提示词不是让模型画“课程插画”或“知识点海报”，而是强调：

- wide horizontal banner
- low-height panoramic feel
- abstract artistic landscape
- scenic / atmospheric / calm / elegant
- subtle relation to course theme
- no text anywhere
- no equations / diagrams / charts / UI

课程相关性只作为“隐喻性线索”，来自：

- `subject`
- `user_prompt`
- `plan_summary`
- `chapter_plan` 的标题与目标

这样可以避免封面变成直白的知识点拼贴图。

## 6. 产物与存储

当前封面图片写入：

- `users/<user>/subjects/<subject>/assets/docgen/docgen_cover_<build_session_id>.<ext>`

当前 sidecar 元数据写入：

- `knowledge_markdowns/_build/cover_artifact.json`

文档顶部插入的 Markdown 形式是：

```md
![](assets/docgen/docgen_cover_<build_session_id>.png)
```

前端会把这个路径解析成受保护资源接口。

## 7. 合成顺序

当前整本文档的前部顺序为：

1. 封面图
2. `# 知识文档总览`
3. `## 目录`
4. 总览正文
5. 各章节
6. 参考资料

这样比“目录压在最前面”更像真实文档结构，也能保证封面始终在顶部。

## 8. 当前取舍

当前实现是一个很稳的 V1，而不是一次性做满：

- 只支持全局开关，不支持单次构建覆盖
- 封面失败不会回滚正文
- 不做复杂封面版本管理
- 不对老版本封面资产做额外清理

这些取舍是有意的，因为这轮重点是：

- 把能力接通
- 不拖慢主链路
- 不让失败扩大 blast radius

## 9. 后续演进

后面如果要升级，推荐顺序：

1. 增加“单次构建是否生成封面”请求字段
2. 增加封面风格枚举，而不是开放自由 prompt
3. 给 `docgen_manifest` 增加更明确的封面元数据
4. 增加旧封面资产清理策略
5. 把封面、图示、练习题统一收敛到更完整的资产 sidecar 编排层
