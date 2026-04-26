# 22. DocGen Build Workspace 初版视觉实现稿

最后更新：2026-04-21

状态：规划中，面向 V1 前端落地

---

## 1. 这份文档解决什么问题

`20_docgen_live_build_experience.md` 已经定义了：

- 用户为什么需要看到构建过程
- Build Workspace 应该承载什么内容
- 如何保证“始终有内容可看”

`21_docgen_build_workspace_experience.md` 已经定义了：

- SSE / polling 的职责边界
- 事件协议最小集合
- 前后端如何做实时状态归并

这份文档进一步回答：

> 初版前端样式到底怎么做，做成什么气质，哪些组件先上，哪些组件复用现有实现，怎样在不推翻当前页面的前提下做出第一版真正可上线的 Build Workspace。

---

## 2. 设计目标

DocGen 工作台的初版视觉实现，需要同时满足 5 个目标：

1. 第一眼就让用户感觉“这是一个正在备课和成文的工作台”，不是普通 loading。
2. 在保留当前工程成本可控的前提下，最大化复用现有 `knowledge-docs` 组件。
3. 中间内容的视觉层级要比进度条更强，让用户先看内容，再看状态。
4. 兼容当前 `KnowledgeDocsPage` 的文档阅读页结构，避免新开第二套页面。
5. 现在先做 polling 也成立，后续接 SSE 时无需重做视觉壳。

---

## 3. 参考与借鉴

这版视觉方案不是凭空想象，而是有意识地吸收了几类成熟产品的优点。

### 3.0 顶级站点基准

V1 不是“参考几个 AI 产品截图”，而是明确对标下面这些顶级站点的长处。

| 站点 | 当前公开口径 | 这次主要借什么 | 明确不借什么 |
| --- | --- | --- | --- |
| Linear | `Built for purpose` / `Powered by AI agents` / `Designed for speed` | 低噪音高效率、状态清晰、工作台节奏感 | 过重的 issue tracker 既视感 |
| Notion AI | `Your AI workspace` / `Meet your 24/7 AI team` | workspace 组织方式、内容优先、模块分区 | 过于通用办公套件化 |
| Claude / Artifacts | artifact 独立产物区、持续迭代 | 主产物优先、成果区不从属于聊天流 | 聊天气泡统治页面 |
| Stripe | 企业级可信赖感、模块节奏和排布控制 | 稳定层级、精致边框、可信任的高级感 | 纯 marketing 官网气质 |
| Vercel / Geist | `care and craft` / consistent web experiences | 精准 spacing、克制组件、细致交互 | 过度极简导致信息失重 |

这 5 个 benchmark 不是让我们做“混搭拼贴”，而是用来校验每个视觉决策是否足够成熟。

### 3.1 Gemini 的可借鉴点

来自 Gemini Canvas 和 Deep Research 的公开资料，可以提炼出 4 个关键点：

- Canvas 强调“右侧独立工作区”，并支持直接编辑、快速改写、实时反映改动。
- Deep Research 强调“先选来源，再开始研究”，用户对来源边界有感知。
- Deep Research 的结果不是停在聊天里，而是收束成一份结构化报告。
- Gemini 在研究和文档之间形成连续体验，而不是“等待页”和“结果页”彻底割裂。

对 AITeachMe 的启发：

- DocGen 过程页不能只是状态流，必须有独立的“成果画布”。
- 工作台里的中间产物必须越来越接近最终知识文档，而不是永远停留在系统日志层。
- “来源感”要明确可见，但不能淹没主内容区。

当前公开资料里，Gemini Canvas 被描述为一个可以直接创建和编辑文档或代码、改动会实时反映的交互空间；Deep Research 则强调来源选择与研究报告化输出，而不是只给一次聊天回答。

参考：

- Gemini Canvas help: <https://support.google.com/gemini/answer/16047321>
- Gemini Deep Research help: <https://support.google.com/gemini/answer/15719111>
- Gemini Canvas blog update: <https://blog.google/intl/ja-jp/company-news/technology/gemini-canvas/>

### 3.2 Claude / Artifacts 的可借鉴点

Claude Artifacts 最值得借鉴的不是“右侧开个面板”这么简单，而是：

- 产物区是独立窗口，不被聊天流淹没。
- 产物可以持续迭代，而不是每次重开一个新结果。
- 右侧产物区支持版本、查看源码、复制、下载等清晰操作。
- 当产物开始生成时，面板就立即打开，而不是等全部完成。

对 AITeachMe 的启发：

- DocGen 的主画布要尽早出现，不要等到文档完整后才出现。
- 章节预览和整本预览要视为“不断被覆盖更新的同一产物”。
- 右侧信息区和主画布必须明确分层，不能全混进同一列。

公开资料里，Claude 产品本身也在强调 projects、tools、web search、artifacts 这类工作流能力，而不是纯聊天盒子。

参考：

- Claude Artifacts help: <https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them>

### 3.3 开源项目的可借鉴点

#### Vercel Chatbot

它的价值在于：

- 基于 Tailwind + shadcn/ui 的构建方式清爽、可维护。
- UI 原子组件克制，不会喧宾夺主。
- 非常适合作为“先搭稳定壳，再逐步丰富能力”的参考。

参考：

- <https://github.com/vercel/chatbot>

#### Obsidian AI

它的价值在于：

- 持久 side panel + artifact tab 的模式非常适合“产物式工作区”。
- 产物一开始写就能打开，不必等生成完。
- 预览与编辑、多个 artifact 并存、实时流式更新的组织方式很清晰。

对 AITeachMe 的启发：

- 章节卡和整本预览可以用“同一工作台中多个产物区域”的方式组织，而不是堆一大串列表。

参考：

- <https://github.com/sup3rus3r/obsidian-ai>

### 3.3.1 Linear / Notion / Stripe / Vercel 的硬借鉴点

这 4 类顶级网站不是用来“看配色”，而是用来校验产品成熟度。

#### Linear

当前官网公开强调：

- `Built for purpose`
- `Powered by AI agents`
- `Designed for speed`

同时页面本身明显体现出：

- 信息密度高，但不乱
- 卡片、时间线、标签和状态都很安静
- 强调主要靠结构和间距，而不是靠很重的颜色

对 AITeachMe 的硬约束：

- 工作台必须有 Linear 式低噪音高效率感
- 同屏组件不能每个都在抢注意力
- feed、章节状态、指标都必须非常清楚

参考：

- <https://linear.app/>

#### Notion

当前 Notion AI 页面直接把自己定义为：

- `Your AI workspace`
- `Meet your 24/7 AI team`

这说明它的设计逻辑不是“一个 AI 功能页”，而是“一个有多种协作对象的工作空间”。

对 AITeachMe 的硬约束：

- DocGen 不该像一个 loading 页面，而该像一个学习工作空间
- 左中右三块区域必须像 workspace，而不是 marketing sections
- 内容区永远优先于装饰性视觉

参考：

- <https://www.notion.com/product/ai>

#### Stripe

Stripe 最值得借鉴的不是渐变，而是：

- 企业级可信赖感
- 极稳的模块节奏
- 强而不吵的视觉层次
- 数字、指标、案例块都很克制

对 AITeachMe 的硬约束：

- Header 和指标区要像 Stripe 一样稳
- 卡片、边框、按钮、信息块不能有廉价感
- 不能靠花里胡哨的背景来制造高级感

参考：

- <https://stripe.com/>

#### Vercel / Geist

Vercel Design 公开写了：

- `care and craft`
- `Geist Design system for building consistent web experiences`

对 AITeachMe 的硬约束：

- V1 要有统一 spacing、统一圆角、统一边框逻辑
- 组件不能出现“每块都不一样”的临时拼接感
- 动效和 hover 必须精细、轻量、可重复

参考：

- <https://vercel.com/design>

### 3.4 Tosea 的可借鉴点

从 Tosea 的公开介绍和博客定位里，可以提炼出两点：

- 它强调从源文档中直接抽取关键洞见、图表和公式，而不是凭空补写。
- 它强调大纲先成形、版式一致、结果持续可精修。

对 AITeachMe 的启发：

- 初版视觉必须强化“source-first”和“结构先成形”的感觉。
- 样式上不要做成炫酷的 AI 表演台，而要做成“可靠、整洁、适合高强度学习”的研究工作台。

参考：

- <https://www.daidu.ai/products/tosea-ai>
- <https://tosea.ai/blog>

---

## 4. 初版视觉方向

### 4.1 总体气质

V1 推荐采用：

> Study Desk + Research Canvas + Quiet Confidence

翻成更具体的话，就是：

- 有文档感
- 有构建感
- 有实时变化
- 但不做“炫技型 AI 控制台”

不建议的方向：

- 赛博紫 + 大量霓虹
- 满屏终端日志
- 聊天气泡占主视觉
- 黑底荧光式 agent dashboard

### 4.2 视觉关键词

- 纸面感
- 石色中性背景
- 天空蓝强调
- 墨色正文
- 温和而明确的层级
- 轻微实验室感，而不是强科技感

### 4.3 一句话视觉判断

用户打开后应该觉得：

> “系统正在为我备一份高质量讲义，而且我已经能看到它正在成形。”

### 4.4 非谈判式视觉约束

下面这些约束是硬规则，不是建议：

1. 不用随意拼接紫色、蓝色、黑色科技风渐变。
2. 不做“AI 控制台”式终端观感。
3. 不允许同一页面出现 3 套以上互相无关的卡片风格。
4. 不允许一个区域一个圆角体系，一个区域一个阴影体系。
5. 不允许把所有信息都做成药丸标签或小卡片，导致页面碎裂。
6. 不允许把进度条做成主视觉，内容却缩成次级信息。
7. 不允许用大量动画掩盖没有内容的问题。
8. 不允许因为想做“高级感”而牺牲中文阅读舒适度。

---

## 5. V1 页面骨架

### 5.1 桌面端布局

推荐布局：

```text
┌──────────────────────────────────────────────────────────────┐
│ Workspace Header                                            │
├──────────────┬───────────────────────────────┬──────────────┤
│ Left Rail    │ Artifact Canvas               │ Right Rail   │
│              │                               │              │
│ 阶段轨道     │ 主预览卡                      │ 实时动态      │
│ 材料入口     │ 章节板 / 大纲 / 合并预览      │ 来源面板      │
│ 模式说明     │ 次级内容区                    │ 陪伴提示      │
└──────────────┴───────────────────────────────┴──────────────┘
```

推荐宽度：

- `Left Rail`: `248px`
- `Right Rail`: `320px`
- `Artifact Canvas`: 自适应主列
- 页面最大宽度：`1440px`

对当前页面的兼容策略：

- 仍在 `KnowledgeDocsPage` 内完成
- 构建态优先单独占据内容区
- 完成后自然切回文档阅读态

### 5.2 平板端布局

平板端不保留完整三栏。

推荐：

- 左 rail 收窄为顶部横向阶段条
- 中间保留主画布
- 右 rail 合并为下方两块折叠卡

### 5.3 移动端布局

移动端推荐：

- 顶部 sticky Header
- 中间单列 `Artifact Canvas`
- 底部 segmented tabs：`进展 / 来源`

不要在手机端保留双侧边栏抽屉式复杂布局。

---

## 6. 初版颜色与字体方案

### 6.1 直接复用现有字体

当前已有：

- `--font-sans: Inter + 中文系统回退`
- `--font-serif: Noto Serif SC / Georgia`

V1 不需要再引入新字体。

用法约定：

- 状态、按钮、指标：`--font-sans`
- 大标题、摘要、草稿片段：`--font-serif`

### 6.2 V1 色板

建议新增一组工作台专用 CSS 变量，但不污染全局主站色板。

建议放在 `frontend/src/index.css`，以 `.doc-build-v1` 或 `:root` 局部变量形式接入：

```css
--build-bg: #f7f6f2;
--build-panel: #fffdf8;
--build-panel-strong: #ffffff;
--build-panel-muted: #f2efe7;
--build-border: #e7e1d3;
--build-border-strong: #d8d1c3;
--build-text: #1f2329;
--build-text-secondary: #626974;
--build-text-tertiary: #8b93a1;
--build-accent: #3b82f6;
--build-accent-soft: #e7f0ff;
--build-success: #16a34a;
--build-success-soft: #eaf8ef;
--build-warn: #d97706;
--build-warn-soft: #fff4df;
```

### 6.3 为什么不用纯白 + 纯蓝

因为 DocGen 的主感觉不是“即时对话”，而是“沉淀型学习文档在成形”。

略带纸感的暖中性色背景有两个好处：

- 草稿区更像文档，而不是管理后台
- 蓝色强调会更克制、更耐看

### 6.4 统一设计 token 规则

为避免“自己乱写”，V1 必须统一下面几类 token：

- 圆角：只允许 `12 / 16 / 20 / 24`
- 边框：只允许 1px 细边框，颜色统一走 `--build-border*`
- 阴影：只允许 2 套，普通卡与强调卡
- 间距：优先用 4 的倍数系统
- 字号层级：正文最多 4 档，不能到处微调

如果某个新组件需要例外，必须先说明为什么当前 token 不够用。

---

## 7. 组件分层与复用策略

### 7.1 当前组件不要推倒

当前已有组件不是废的，V1 推荐做“壳层重组”：

- `BuildView` 继续保留，但升级成新的 Workspace Shell
- `BuildProcessTimeline` 升级为阶段轨道
- `BuildMaterialPipeline` 升级为左 rail 的材料区
- `BuildLiveDraft` 合并进主画布
- `BuildMetricsBadges` 合并进 Header
- `BuildResearchSources` 拆分

### 7.2 推荐的新组件结构

```text
knowledge-docs/
  BuildWorkspaceShell.tsx
  BuildWorkspaceHeader.tsx
  BuildStageRail.tsx
  BuildArtifactCanvas.tsx
  BuildPlanSnapshot.tsx
  BuildChapterBoard.tsx
  BuildMergePreview.tsx
  BuildLiveFeed.tsx
  BuildSourcePanel.tsx
  BuildTriviaPanel.tsx
```

### 7.3 现有组件映射

| 现有组件 | V1 去向 |
| --- | --- |
| `BuildView` | 保留，但改成容器壳 |
| `BuildProcessTimeline` | 作为 `BuildStageRail` 基础 |
| `BuildMaterialPipeline` | 作为左侧材料区基础 |
| `BuildLiveDraft` | 合并进主画布的草稿区 |
| `BuildMetricsBadges` | 进入顶部 Header |
| `BuildResearchSources` | 拆为 `BuildLiveFeed` 和 `BuildSourcePanel` |

---

## 8. 每个区域的具体样式实现

### 8.1 Workspace Header

#### 目标

让用户 2 秒内知道三件事：

- 现在在做什么
- 大概做到哪了
- 这轮文档是什么模式

#### 结构

```text
Build badge + 标题 + 当前阶段描述
Progress bar
Metrics badges
Mode chip / chapter count / source count / updated time
```

#### 样式建议

- 外层：圆角 `24px`，浅暖底，轻边框
- 顶部 badge：`Sparkles + 知识构建`
- 标题：`text-2xl font-semibold`
- 阶段描述：`text-sm text-secondary`
- 进度条：细线型，不要过厚
- 指标 badge：白底小药丸，不超过 4 个

#### 不建议

- 顶部整块做成深色 hero
- 进度数字比标题还抢眼
- 左右信息塞得像 dashboard 顶栏
- 同时放 8 个以上 badge

### 8.2 Left Rail

#### 包含内容

- 阶段轨道
- 材料卡片列表
- 构建模式说明卡

#### 样式建议

- 使用竖向卡片堆叠
- `sticky top-6`
- 阶段轨道卡和材料卡分开

#### 阶段轨道视觉

- 当前阶段用蓝色实心圆点 + 轻脉冲
- 已完成阶段用绿色对勾圆点
- 未开始阶段用浅灰描边点
- 左侧竖线保持很细，弱存在感

要更接近 Linear，而不是更接近常见 BI 系统。

#### 材料列表视觉

- 每个文件是一张小卡，而不是单行列表
- 文件图标放左侧固定 32px 容器
- 卡片底部可显示极细进度线

### 8.3 Artifact Canvas

这是 V1 的重点区域。

推荐分两层：

- 上层：当前主产物
- 下层：次级辅助产物

#### 冻结方案阶段

主产物：

- `BuildPlanSnapshot`

内容：

- `plan_summary`
- digest mode
- chapter count
- 一屏内可见的章节标题清单

视觉：

- 像“课程讲义封面页 + 目录预告”
- 标题用 serif
- 章节列表用轻量 pill 或序号卡

#### 理解资料 / 构建骨架阶段

主产物：

- `BuildOutlineSnapshot`

次级产物：

- 文件理解卡片网格

视觉：

- 上面是章节结构
- 下面是 2 列材料卡
- 让用户感觉“资料已被系统整理成课程结构”

#### 并行写作阶段

主产物：

- `BuildChapterBoard`

次级产物：

- `BuildLiveDraft`

推荐样式：

- 上半部分：章节板，2 列或 3 列小卡
- 下半部分：当前活跃章节的草稿片段

章节卡片字段：

- 章节序号
- 标题
- 状态
- 字数
- 来源数
- 最新小标题
- 可选短摘录

活跃章视觉：

- 蓝色边框
- 顶部有轻微 gradient highlight
- 卡片阴影略高于其他章

但 gradient 只能作为 10%-15% 的轻强调，不允许变成营销海报。

已完成章视觉：

- 边框变淡
- 状态点变绿

#### 复核回流阶段

主产物：

- `BuildReviewSnapshot`

内容：

- 复核完成章节数
- 当前 review decision
- warning 摘要

视觉：

- 不要展示内部 review trace
- 应该像“老师在统稿”的状态卡

#### 合并发布阶段

主产物：

- `BuildMergePreview`

内容：

- 最新章节标题
- merged excerpt
- 发布状态

视觉：

- 让页面开始逼近最终文档阅读样式
- 草稿预览区域应比前几个阶段更“像文档正文”

### 8.4 Right Rail

推荐拆成三块：

- `BuildLiveFeed`
- `BuildSourcePanel`
- `BuildTriviaPanel`

#### BuildLiveFeed

作用：

- 告诉用户刚刚发生了什么

样式：

- 时间轴卡片
- 每条事件 1 句摘要为主
- 只保留 8-10 条

#### BuildSourcePanel

作用：

- 告诉用户这轮文档主要依赖哪些来源

样式：

- domain chip
- source title
- chapter relation label

不要和 LiveFeed 混用同一种卡。

#### BuildTriviaPanel

作用：

- 填补等待中的认知空白

实现：

- 前端本地静态数据
- 12-18 秒轮换
- 构建完成时自动隐藏

---

## 9. 动效方案

### 9.1 动效目的

动效只做三件事：

1. 证明系统还活着
2. 告诉用户哪一块刚更新
3. 提升切换阶段时的连续性

### 9.2 推荐动效

- Header 渐入：`200-300ms`
- 章节卡新增：`opacity + y + scale`
- feed 新事件：从下往上淡入
- 进度条：缓动宽度变化
- 当前阶段圆点：低频脉冲
- 草稿光标：已有 `animate-blink` 即可

### 9.3 不建议

- 大面积 shimmer
- 强 bounce
- 满屏粒子或流光
- 多个区域同时高频动画

这条要严格执行。顶级网站的“贵”通常来自克制，而不是来自动得很多。

---

## 10. 初版交互规则

### 10.1 中央画布优先级

规则：

- 有主产物时，主产物永远占上半屏
- feed 和来源永远不能抢主产物的高度

### 10.2 阶段切换时不清空页面

规则：

- 旧阶段主产物退为次级区域
- 新阶段主产物替换上方内容
- 页面不能因为状态切换重新只剩进度条

### 10.3 章节板排序固定

章节卡按 `chapter_index` 固定排序。

不能按事件到达顺序乱跳。

### 10.4 构建完成后的切换

完成时不跳出新页面。

推荐行为：

- Header 变成“最新知识文档已发布”
- 主画布淡入最终文档阅读态
- 右侧实时区弱化或收起

---

## 11. 移动端收敛方案

移动端只保留 3 块核心：

1. `Header`
2. `Artifact Canvas`
3. `Bottom Info Tabs`

建议底部 tabs：

- `进展`
- `来源`

移动端不保留：

- 双侧栏同时展开
- 复杂 hover
- 多层 sticky 容器

---

## 12. 文件级实现建议

### 12.1 第一轮最小文件改动

建议优先涉及：

- `frontend/src/components/knowledge-docs/BuildView.tsx`
- `frontend/src/components/knowledge-docs/BuildProcessTimeline.tsx`
- `frontend/src/components/knowledge-docs/BuildResearchSources.tsx`
- `frontend/src/components/knowledge-docs/BuildLiveDraft.tsx`
- `frontend/src/components/knowledge-docs/BuildMetricsBadges.tsx`
- `frontend/src/pages/KnowledgeDocsPage.tsx`
- `frontend/src/index.css`

### 12.2 第一轮建议新增组件

- `BuildWorkspaceHeader.tsx`
- `BuildArtifactCanvas.tsx`
- `BuildChapterBoard.tsx`
- `BuildLiveFeed.tsx`
- `BuildSourcePanel.tsx`
- `BuildTriviaPanel.tsx`

### 12.2.1 第一轮应优先重写的而不是“继续凑合”的组件

这几块即使现有实现可用，也建议按新基准重写视觉层：

- `BuildView`
- `BuildResearchSources`
- `BuildProcessTimeline`

理由：

- 它们直接决定第一屏观感
- 最容易暴露“像临时拼出来的”
- 也是最容易被用户判断高级感的区域

### 12.3 可以暂缓的内容

- 多 artifact tabs
- 章节预览 diff
- 复杂版本选择器
- 真正的 SSE 实时 reducer UI

---

## 13. 分阶段实现建议

### Phase A：纯视觉壳重组

目标：

- 不改数据协议
- 先把 `BuildView` 变成更清晰的三栏 Workspace
- 完成 `LiveFeed / Sources` 拆分

### Phase B：补画布级组件

目标：

- 引入 `BuildPlanSnapshot`
- 引入 `BuildChapterBoard`
- 引入 `BuildMergePreview`

### Phase C：补专用 token 和细节动效

目标：

- 接入工作台专用色板
- 统一卡片、边框、字体层级
- 清理旧的随机 stone/zinc/sla​​te 组合

### Phase D：接 SSE

目标：

- 保持壳不变，只换数据流
- 让 feed / chapter board / merge preview 实时动起来

---

## 14. 初版验收标准

V1 样式实现至少要满足：

1. 构建态页面不再像“一个大进度条包着几个小组件”。
2. 用户第一眼能区分：阶段轨道、主画布、实时动态、来源面板。
3. 中央画布在不同阶段确实展示不同内容，而不是同一块文案反复换标题。
4. 页面整体气质更像“备课/成文工作台”，而不是聊天窗口。
5. 桌面端和移动端都能工作，且移动端不是桌面布局硬压缩。
6. 后续接 SSE 时，不需要推倒视觉层。

---

## 15. 一句话结论

DocGen 工作台的初版样式，最重要的不是“高级感”，而是：

> 让用户稳定地看到一份学习文档是如何从方案、资料、章节草稿一路长成正式讲义的。
