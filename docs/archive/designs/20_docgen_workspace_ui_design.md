# AITeachMe DocGen Build Workspace: UI/UX & Aesthetics Design

最后更新：2026-04-21

本文档浓缩了知识文档构建（DocGen）过程前端展示的 UI/UX 设计方案，核心目标是解决原有页面“纯等待态、视觉单调、缺乏反馈”的问题，将其重构为一个高级、美观、充满“陪伴感”的**构建工作台（Build Workspace）**。

---

## 1. 设计核心理念与美学 (Aesthetics & Principles)

既然主打“赛博私教”，构建过程就不应该是一个冷冰冰的“进度条”。用户需要亲眼看到知识从无到有、从混乱到有序的**编织过程**。

### 1.1 美学原则 (Aesthetic Guidelines)
- **高级感与清晰度 (Premium & Crisp)**：避免采用纯色块堆砌。使用精致的边框（`border-stone-200/60`）、细微的阴影（`shadow-sm` 到 `shadow-xl` 过渡）、毛玻璃效果（Glassmorphism，`backdrop-blur-md`），营造出现代化工作区的质感。
- **排版为王 (Typography-led)**：正文与大纲使用具有阅读质感的衬线/无衬线混合排版（`font-serif` 标题搭配 `font-sans` 正文），让“草稿”看起来就像是排版精美的电子书，而不是程序的终端输出。
- **微动效与秩序感 (Micro-animations)**：拒绝满屏刺眼的强闪动。大量使用 Framer Motion 的 `layout` 平滑过渡、列表项的交错淡入（staggered fade-in，`delay: index * 0.1`），以及活泼但不过分的生动效果（如：状态指示小圆点的呼吸灯效果）。
- **让用户“始终有东西看”**：无论何时，屏幕中央（画布区）必须有当前最高价值的产出物。绝对不能让核心区域出现大面积留白。

---

## 2. 三栏式剧场布局 (Three-Column Theater Layout)

前端入口收敛：**`KnowledgeDocsPage` 成为唯一的构建与阅读工作台。**

页面采用经典且专业的三列式布局（在移动端降级为抽屉或 Tab）：

### 左栏：施工轨道 (Build Stage Rail)
**宽度**: `~260px`
**定位**: `sticky`，随页面滚动。
**内容**: 
展现 DocGen 的高阶生命周期。抛弃底层 LangGraph 节点名，采用用户可视化的节点：
1. 📝 **提取资料核心** (Ingest & Understand)
2. 🕸️ **编织知识骨架** (Outline & Backbone)
3. ✍️ **发散撰写章节** (Parallel Drafting)
4. 🔍 **一致性复核** (Review & Repair)
5. 📚 **合卷与排版** (Merge & Publish)
**视觉**: 激活状态带有柔和的发光背景（`bg-sky-50/50`），完成状态有顺滑的打钩动画（Spring 动画）。

### 中栏：核心产物画布 (Artifact Canvas)
**宽度**: `自适应 (1fr)`，最小限度留白，居中对齐。
**定位**: 视觉重心。
**内容机制**:
根据左侧当前所在的阶段，画布**动态切换**内容，始终展示当下最核心的中间资产：
- **阶段 1 时**：展示精致的【资料透视卡片】（每份文件的核心摘要与标签）。
- **阶段 2 时**：展示【可视化知识骨架】（带有连线的章节依赖树或大纲列表）。
- **阶段 3 时**：展示【打字机效果的草稿面板】（各个章节并行生长的卡片矩阵，显示字数与进度）。
- **阶段 4、5 时**：展示接近最终阅读版的【文档合卷预览】（使用实际 Markdown 渲染器，带有高光标记）。

### 右栏：动态与溯源 (Live Feed & Source Panel)
**宽度**: `~320px`
**内容**:
- **上部 - 实时动态 (Live Feed)**：SSE 推送的轻量解释性事件。如“✨ 发现核心概念：极限”，“✍️ 正在撰写第 2 章”。列表向上滚动，顶部最新，具有淡出（fade-out）遮罩。
- **下部 - 灵感溯源 (Sources)**：展示当前正在依赖的外部资料、图表或概念源。如果是文档，展示文档切片缩略图；如果是网页，展示网站 Favicon 及标题。
- *(可选) 陪伴区*：底部放置随机渲染的“教育名言”或“认知科学 Tips”，极大地缓解长任务焦虑。

---

## 3. UI 组件拆解规划

我们将把巨石组件 `BuildView.tsx` 拆分为以下结构：

```text
KnowledgeBuildWorkspace/
  ├── BuildWorkspaceHeader      # 顶部标题与全局进度条 (极细的顶轨进度条)
  ├── BuildStageRail          # 左栏：脉络进度条
  ├── BuildArtifactCanvas     # 中栏：多形态中间产物画板
  │     ├── InsightsBoard     # 形态 1：资料摘要看板
  │     ├── OutlineBoard      # 形态 2：大纲树
  │     ├── DraftMatrix       # 形态 3：章节卡片矩阵
  │     └── MergedPreview     # 形态 4：合卷预览
  ├── BuildFeedAndSources     # 右栏：融合组件
        ├── LiveFeedList      # SSE 实时日志留痕
        └── RelevantSources   # 当前参考来源
```

---

## 4. 样式优化的具体落地策略

1. **剔除原生滚动条**：使用自定义的、自动隐藏的透明滚动条，保持画面极度纯净。
2. **Glassmorphism 卡片**：画布内的卡片统一采用 `bg-white/70 backdrop-blur-md border border-white/20 shadow-xl shadow-sky-900/5`。
3. **颜色基调**：
   - 主色调：`Sky` (代表清晰、智慧)与 `Zinc/Stone` (代表专业、纸张)。
   - 点缀色：`Emerald` (成功/复核完成)、`Violet` (AI 理解中)。
4. **加载空态 (Skeleton)**：当某一阶段刚切换、内容还没回来时，展示带有渐变流水光的骨架屏（Shimmer），但轮廓与实际内容 100% 对齐，防止布局跳动（Layout Shift）。

> **一句话总结**: 整个 UI 的使命，是让这个 2-5 分钟的漫长等待，变成一次令人赏心悦目的“知识艺术展”。
