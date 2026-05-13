# 英文模式与国际化策略

最后更新：2026-05-13

本文定义 AITeachMe 是否需要英文模式、英文模式到底包含什么，以及后续改造时应放在哪些目录里。

## 结论

建议做，但不要一上来做完整多语言重构。

短期最有价值的是先让项目对外表达 English-ready：补英文 README / 项目介绍 / 演示材料，让海外开发者、评审、论文审稿人能看懂项目。完整英文模式要分阶段做，因为它不只是把按钮翻译成英文，也不只是把 prompt 改成英文。

真正的英文模式至少包含四层：

1. UI 语言：按钮、菜单、空状态、设置项、错误提示、进度文案。
2. 生成物语言：知识文档、学习计划、考试反馈、画像总结等面向学习者的内容。
3. Prompt 语言策略：每条 workflow prompt 都能明确目标输出语言，并处理资料语言和用户语言不一致的情况。
4. API / 事件语言契约：请求、SSE、progress event、错误响应都能知道应该面向哪个 locale 输出。

所以英文模式不等于把所有 prompt 常量整体翻译成英文。更稳妥的做法是：系统提示词可以继续用稳定、模型效果好的语言写，但必须显式传入 `target_language` / `response_language`，要求最终用户可见内容按目标语言输出。

## 工程原则

英文模式应按 AITeachMe 自己的产品闭环设计，而不是照搬外部项目。

- 根 README 和对外材料负责让外部读者快速理解项目。
- 前端 i18n 应有独立目录和稳定 locale registry，不应把翻译散落在组件里。
- Prompt 应保留在 workflow lane 内，由业务 owner 维护；跨 workflow 只共享语言策略片段。
- 自动语言推断应服务生成物语言选择，不能替代用户显式设置。
- UI i18n、prompt 模板、语言推断是三件有关联但分层的事。不能只翻译前端，也不能把所有 prompt 按语言复制多份。

## AITeachMe 的推荐阶段

### Phase 0：英文对外材料

目标是先服务开源展示、论文评审、外部合作和 GitHub 访客。

- 新增 `README.en.md` 或改成根 README 英文、`README.zh-CN.md` 中文。
- 保留中英文切换链接。
- 英文版只写对外事实：产品定位、核心闭环、架构、快速启动、部署方式、路线图、引用方式。
- 不要求 UI 已经支持英文。

如果当前主要用户仍是中文，根 README 可以继续中文，先加 `README.en.md`。如果目标是国际开源传播，后续可以反过来让根 README 英文、中文放 `README.zh-CN.md`。

### Phase 1：前端 UI i18n 外壳

目标是让新增 UI 文案不再继续硬编码。

推荐结构：

```text
frontend/src/
  i18n/
    index.ts
    locales/
      zh-CN.ts
      en-US.ts
    keys.ts
  components/settings/
    LanguageSettings.tsx
```

约束：

- `frontend/src/api/generated/` 仍然不手改。
- 先覆盖全局导航、设置、首页、课程列表、通用按钮、空状态和错误提示。
- 业务深页面可以逐步迁移，不要一次性机械替换所有中文字符串。
- 日期、数字、文件大小等格式化使用 locale-aware API，而不是手写字符串拼接。

### Phase 2：后端用户可见消息语言契约

目标是让 API、SSE、progress event 不再默认只能中文。

建议引入请求级语言上下文：

```text
locale           UI locale，例如 zh-CN / en-US
response_language 用户可见自然语言输出，例如 Chinese / English
source_language 资料语言，可由 ingest 检测得出
```

注意：

- `locale` 是界面和事件展示语言。
- `response_language` 是 LLM 输出语言。
- `source_language` 是资料本身语言，不应该被强制翻译掉。
- 如果没有显式选择，优先从用户输入和资料语言推断；推断不稳定时回退中文。

### Phase 3：Prompt 语言策略

目标是让各 workflow prompt 统一声明“最终面向用户的输出语言”，但仍保留 lane 内 prompt ownership。

推荐结构：

```text
backend/app/workflows/common/
  language_policy.py       # 只放跨 workflow 的语言解析和 prompt 片段构建

backend/app/workflows/<engine>/<lane>/prompts/
  ...                      # 仍然保留各 lane 自己的业务 prompt
```

不要新增一个全局 `prompts/` 目录接管所有业务 prompt。AITeachMe 现在的结构是按 workflow lane 拥有 prompt，这个边界是对的。跨 workflow 的公共部分只应包括语言名称标准化、目标语言说明、fallback 策略和测试辅助。

### Phase 4：生成物与导出

目标是让用户真正感受到英文模式。

需要覆盖：

- Digest：学习方案、知识文档、质量报告。
- Interact：伴读回答、引用说明、追问。
- Examine：题干、选项、评分反馈、错因解释。
- Profile：学习画像、复习任务、study plan。
- Export / import：导出的 Markdown / `.atmx` 元信息中记录语言。

原则：

- 引用和原文片段保持原语言。
- 总结、解释、教学建议按 `response_language` 输出。
- 双语资料不强行翻译成单语，先保证可解释和可追溯。

### Phase 5：验证矩阵

英文模式必须有最小验证矩阵，不能只靠肉眼检查首页。

建议至少覆盖：

```text
UI: zh-CN / en-US
资料: 中文资料 / 英文资料
用户问题: 中文 / 英文
输出: 知识文档 / 对话 / 考试反馈 / study plan
```

每个组合至少检查：

- 页面不溢出、不混杂明显错误语言。
- progress event 和错误提示跟随 locale。
- LLM 最终用户可见输出跟随 response_language。
- 引用、来源、文件名不被错误翻译。

## 现在不建议做的事

- 不建议马上把所有中文 UI 文案一次性抽成 key；这会制造大量低价值 diff。
- 不建议复制一套 `prompts_en/` 和 `prompts_zh/`；后续维护成本会很高。
- 不建议让 `shared.infra` 感知教学语言策略；infra 只负责能力接入，不负责教学语义。
- 不建议把资料内容强制翻译成目标语言后再入库；这会破坏引用和可追溯性。
- 不建议只做“英文按钮”，然后宣称支持英文模式；生成物和 prompt 策略才是学习产品的核心。

## 推荐优先级

1. 先补英文 README / 项目展示材料。
2. 再补前端 i18n 外壳和语言设置入口。
3. 然后让 progress event、错误提示、chat/docgen/exam/profile 的用户可见输出接入语言契约。
4. 最后再系统性迁移 prompt 语言策略和测试矩阵。
