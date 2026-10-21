# Multimodal DocGen 链路

这是与 `digest/docgen` 并列的独立可选链路。原 DocGen Graph、State 和节点行为不做修改。

当前已完成：生成可缓存的 `VisualEvidence`、用于 Section 到章节的路由、把已路由图片作为本地视觉证据加入逐章上下文，以及 Writer 按需直接复读少量原图。

```text
load_context
  -> [prepare_visual_evidence || lock_titles_for_chapters]
  prepare_visual_evidence -> prepare_global_seed
  [prepare_global_seed + lock_titles_for_chapters] -> 后续 DocGen
  -> 逐章研究（正文 + 图片文字证据）
  -> Writer（dense_context + 被严格筛选的少量原图）
```

## 当前边界

- 新链路拥有独立 `graph.py` 和 `state.py`。
- 章节编排和 Writer 在本目录独立实现，保留原流式输出、正文清理和重试行为；其它不涉及图像的节点只读复用原链路实现。
- 首页与构建方案页提供默认关闭的「图片理解」开关。关闭只分析文本；开启会分析图片，但会增加耗时。选择保存于课程 `settings_json.digest.image_understanding_enabled`，刷新后恢复。
- 构建 API 可显式传入 `image_understanding_enabled`，省略时使用课程设置；接收请求时固定本次模式并由生命周期层分发到对应 Graph。没有本地资料或已确认全部没有图片时，自动使用原文本链路。构建途中修改课程设置不会改变正在执行的任务。
- 图片阶段记录可轮询、可通过现有 SSE 获取的进度「正在理解资料图片 · 已处理/总数」。已缓存、无意义及处理失败的图片均计入已处理数量。
- `prepare_visual_evidence` 使用 `model="light"`，由设置中的 `models.light` 解析实际模型。
- 图片请求固定使用 `detail="high"`。
- 图片按 Markdown 出现顺序关联到文件和 Section。
- 首次读图同时判断是否有意义、生成文字证据，并决定 Writer 是否需要复读原图；同一请求中同一 Section 的完整正文只提供一次，用于判断正文是否已经覆盖图中知识。
- 缓存键包含图片哈希、完整 Section 正文及附近正文哈希、模型、Prompt 版本和 detail。当前 Prompt 为 `visual-evidence-v4`，旧版缓存不会误用。
- 只有教学相关图片进入 `visual_evidence_items`。
- 封面、Logo、装饰图、无关 UI 等只缓存 `is_meaningful=false`，不进入后续 State。
- 图片读取或视觉模型失败只记录降级信息，不阻断后续文字链路。
- 仅新链路的文件摘要路由会读取视觉证据；按 `file_id + section_ref` 附在发给模型的对应 Section 后。原始 Section、行号、切片目录和原 DocGen 链路均不更改。
- 图片摘要不是可按行号引用的原文；Writer 默认读取结构化的文字版视觉证据。
- 每章只读取该章 `source_slices` 所属 Section 的视觉证据，并将其作为独立本地切片加入优先上下文和内存 RAG。
- 视觉来源使用 `local://file/{file_id}/section/{section_ref}/image/{image_id}`，进入 `dense_context`、`source_details` 和 evidence ledger。
- 每章最多加入 8 张图片、最多约 6000 字符的视觉证据，避免挤占主要正文上下文。

## Writer 原图复读规则

- 首次读图返回 `reread_recommended`、一句话 `reread_reason` 和分项判断 `reread_assessment`，与原有 `VisualEvidence` 一起缓存；默认不复读，不增加模型调用。
- 必须同时满足三项检查：`knowledge_scope=source_specific`（教学重要且不能靠通用知识还原）、`text_coverage=missing`（所属 Section 原始正文未表达）、`original_required=true`（本次已提取的文字证据仍不能可靠保留关键知识）。还必须给出具体缺失知识及需要看原图的原因；代码在返回解析及 Writer 载图前都检查这些条件。
- 标准 Transformer、普通滑动窗口、常见分类思维导图、通用公式及只标常规符号的几何图默认不复读。配色、布局、标签位置、符号命名和“图很复杂”不构成资料独有知识。
- 少量数值或简单连接若已能由本次文字证据完整表达，也不再读取原图；专有架构的复杂连接、密集实验数据的联合比较等确实仍需原图核对时才保留。
- 正文仅提到模型名称或整体目的不算覆盖独有细节；是否足够使用文字，按后续精简的图片证据判断，不能假定完整转录都能送到 Writer。
- 判断缺失、任一项不确定、理由为空或旧状态没有分项检查时，按不复读处理；图片文字证据仍参与后续章节生成。无意义图片仍只保留否定判断，不进入后续链路。
- Writer 只接收本章已选 Section、且实际进入章节来源的图片。按 Section 相关度、教学价值和置信度排序；所有模式统一每章最多 2 张，同一原图去重。
- 原图沿用受控资产读取及预处理，固定 `detail="high"`。图片直接附在 Writer 原有正文请求中，让 Writer 一边看图一边写正文，不再增加一次图片描述或证据生成调用。
- 带图请求使用 Chat Completions，避免共享 Responses 适配器无法转换图片块；纯文本请求保留原有 API 路由。Writer 模型仍按原 DocGen 写作策略选择，首次读图仍统一使用 light。
- 图片无法加载、已经变更或超过预算时跳过原图，仍使用已有文字证据；带图调用失败或无正文时，退回纯文本 Writer。原有流式输出与 Markdown 重试保留。
- base64 仅存在于临时请求内，不写入 State 或证据缓存；LangSmith 请求内容使用现有脱敏机制。章节 `source_scope` 记录实际复读图片、尝试图片、加载失败原因和是否退回文字，便于查看。

## 当前尚未完成

- 视觉证据尚未写入持久化向量索引；当前通过逐章优先上下文和本地 Section fallback 参与检索。
- 尚未实现最终知识文档中的原图展示。

这些步骤会在确认章节路由的图文输出质量、成本和缓存行为后继续接入。
