# Digest 统一构建 - 完整实施报告

## 执行摘要

本次实施完成了知识文档（docgen）和知识图谱（KG）的协同构建架构设计和核心代码实现。

**核心成果**：
- ✅ 完整的架构设计文档（19KB）
- ✅ 共享准备层实现（6 个模块）
- ✅ 构建协调层实现（7 个模块）
- ✅ 一致性校验机制
- ✅ 快速开始指南

**核心优势**：
1. 消除重复劳动（文件读取、清洗、切分）
2. 建立跨 lane 的共享 identity
3. 双向增强（文档利用图谱，图谱利用文档）
4. 自动一致性校验和修复
5. 充分利用 ingest 产出的 assets

## 详细成果

### 1. 设计文档（3 份）

| 文档 | 大小 | 内容 |
|------|------|------|
| `06_digest_unified_build.md` | 19KB | 完整架构设计 |
| `06_digest_unified_build_summary.md` | 5.2KB | 实施总结 |
| `06_digest_unified_build_quickstart.md` | 4.8KB | 快速开始指南 |

### 2. 共享准备层（6 个模块）

```
backend/app/workflows/digest/shared/
├── __init__.py              # 模块导出
├── models.py                # 数据模型（SourcePacket, SectionPacket 等）
├── prepare.py               # 主流程（prepare_shared_inputs）
├── section_splitter.py      # 切分逻辑（split_into_sections）
├── asset_indexer.py         # 资源索引（build_asset_registry）
└── hint_extractor.py        # 提示提取（extract_fast_topic_hints）
```

**核心功能**：
- 一次性加载和规范化 markdown
- 稳定的 section packet 切分（带 digest_chunk_uid）
- Assets 图片索引（充分利用 ingest 产出）
- 轻量级主题提示（规则提取，不调 LLM）
- 跨 lane 的 chunk identity 映射

### 3. 构建协调层（7 个模块）

```
backend/app/workflows/digest/build/
├── __init__.py              # 模块导出
├── runtime.py               # 顶层协调器（run_unified_digest_build）
├── state.py                 # 状态模型（UnifiedBuildState, UnifiedBuildResult）
├── models.py                # 协作模型（ChapterPriors, TopicAnchorSnapshot 等）
├── events.py                # 事件定义
├── artifacts.py             # 工件管理（publish_artifact, try_read_artifact）
└── consistency.py           # 一致性校验（check_consistency, bounded_repair）
```

**核心功能**：
- 双车道并行执行（doc lane + kg lane）
- 软协作机制（超时降级，不互相阻塞）
- 工件发布和读取（跨 lane 通信）
- 覆盖缺口检测（4 类 gap）
- 有预算上限的局部修复

### 4. 协作机制

| 协作点 | 方向 | 超时 | 作用 |
|--------|------|------|------|
| FastTopicHints | shared → doc | 0ms | 优化大纲规划 |
| ChapterPriors | doc → kg | 300ms | 减少 topic 命名漂移 |
| TopicAnchorSnapshot | kg → doc | 500ms | 发现文档缺口 |
| AssetRegistry | shared → 两者 | 0ms | 充分利用图片 |

### 5. 一致性校验

**检测规则**：
1. Doc over graph gaps：章节核心词缺图谱锚点
2. Graph over doc gaps：高置信度节点无文档归属
3. Orphan signals：例子/定义很多但概念薄弱
4. Taxonomy drifts：文档和图谱命名分裂

**修复策略**：
- 最多重写 2 个章节
- 最多重抽 4 个 chunk
- 最多额外 5 次 LLM 调用
- 局部修复，不全量回滚

## 架构图

```
POST /knowledge/build
  ↓
run_unified_digest_build()
  ↓
┌─────────────────────────────────────────────────┐
│  Phase 1: Shared Prepare Layer                  │
│  ├─ Load raw files (parallel I/O)               │
│  ├─ Normalize markdown (rule-based)             │
│  ├─ Split into section packets                  │
│  ├─ Build chunk identity map                    │
│  ├─ Extract fast topic hints (no LLM)           │
│  └─ Index assets (from ingest)                  │
├─────────────────────────────────────────────────┤
│  Phase 2: Dual Lane (Parallel)                  │
│  ┌──────────────────────┐  ┌─────────────────┐ │
│  │  Doc Lane            │  │  KG Lane        │ │
│  │  ├─ Load from shared │  │  ├─ Load shared│ │
│  │  ├─ Outline (hints)  │  │  ├─ Prepare    │ │
│  │  ├─ Draft (assets)   │  │  ├─ Extract    │ │
│  │  ├─ Review (topics)  │  │  ├─ Cluster    │ │
│  │  └─ Publish          │  │  ├─ Resolve    │ │
│  │                       │  │  └─ Finalize   │ │
│  └──────────────────────┘  └─────────────────┘ │
│         ↓ ChapterPriors          ↓              │
│         ↑ TopicAnchorSnapshot    ↑              │
├─────────────────────────────────────────────────┤
│  Phase 3: Consistency Check                     │
│  ├─ Detect doc over graph gaps                  │
│  ├─ Detect graph over doc gaps                  │
│  ├─ Detect orphan signals                       │
│  └─ Detect taxonomy drifts                      │
├─────────────────────────────────────────────────┤
│  Phase 4: Bounded Repair (if gaps exist)        │
│  ├─ Rewrite chapters (max 2)                    │
│  ├─ Reextract chunks (max 4)                    │
│  └─ Budget limit (max 5 LLM calls)              │
├─────────────────────────────────────────────────┤
│  Phase 5: Finalize & Publish                    │
│  ├─ Publish docs                                │
│  ├─ Activate graph                              │
│  └─ Trigger curriculum                          │
└─────────────────────────────────────────────────┘
```

## 性能优化

### 并行度提升

| 阶段 | 并发度 | 说明 |
|------|--------|------|
| 共享准备层 | 10 | 文件读取并行 |
| Doc lane | 10 | 章节写作并行 |
| Doc lane | 10 | 章节审校并行 |
| KG lane | 10 | chunk 抽取并行 |
| KG lane | 8 | 节点消歧并行 |

### 预期性能

- **共享准备层**：< 5s（10 个文件）
- **总体构建时间**：≤ 现有流程的 110%
- **并行效率**：doc/kg lane 真正并行

## 质量提升

### 覆盖率提升

- **文档-图谱覆盖率**：目标 > 80%
- **Topic 命名一致性**：目标 > 70%
- **Assets 利用率**：目标 > 60%

### 一致性保证

- **自动检测**：4 类覆盖缺口
- **自动修复**：有预算上限的局部修复
- **可追溯**：完整的 coverage report

## 待完成工作

### Phase 1：改造 Doc Lane（优先级：高）

需要改造 5 个节点：

1. **load_files_node.py**
   - 从共享层加载 `SourcePacket` 和 `SectionPacket`
   - 不再直接读取文件

2. **cleanse_node.py**
   - 简化为只做 docgen 专属的教学性增强
   - 去掉重复的基础清洗

3. **outline_reduce_node.py**
   - 使用 `FastTopicHints` 作为 soft priors
   - 发布 `ChapterPriors` 给 KG lane

4. **draft_node.py**
   - 利用 `image_refs` 引用 assets
   - 输入包含 `digest_chunk_uid`

5. **review_node.py**
   - 接收 `TopicAnchorSnapshot`
   - 检测覆盖缺口

### Phase 2：改造 KG Lane（优先级：高）

需要改造 3 个节点：

1. **prepare_nodes.py**
   - 从共享层消费 `SectionPacket`
   - 按需物化 `DocumentChunk`

2. **extractor.py**
   - 接收 `ChapterPriors` 作为 taxonomy hint
   - 早期发布 `TopicAnchorSnapshot`

3. **finalize_nodes.py**
   - 发布最终 `TopicAnchorSnapshot`
   - 协调 build session

### Phase 3：API 层整合（优先级：中）

1. 修改 `backend/app/api/knowledge.py`
   - `knowledge_build()` 调用新接口

2. 修改 `backend/app/services/knowledge/digest_service.py`
   - 新增 `run_unified_digest_build_background()`
   - 保留旧接口作为兼容层

3. 添加环境变量开关
   - `USE_UNIFIED_BUILD=true/false`

### Phase 4：测试验证（优先级：高）

1. **单元测试**
   - 共享层：section 切分、hint 提取
   - 协调层：工件读写、一致性检测

2. **集成测试**
   - 端到端构建流程
   - 协作机制验证

3. **性能测试**
   - 对比新旧流程耗时
   - 验证并行度提升

4. **质量测试**
   - 覆盖率统计
   - 一致性准确率

## 技术亮点

1. **共享 Identity**
   - 通过 `digest_chunk_uid` 实现跨 lane 追踪
   - 格式：`rf_{file_id}_sec_{index}_{hash}`

2. **Assets 无损利用**
   - 充分利用 ingest 提取的图片
   - 自动索引和引用

3. **软协作机制**
   - 超时降级，不互相阻塞
   - 等到就用，等不到就降级

4. **局部修复**
   - 有预算上限，可控风险
   - 只修复高优先级缺口

5. **可回退设计**
   - 保留旧接口
   - 环境变量开关
   - 分阶段实施

## 风险与缓解

| 风险 | 影响 | 缓解措施 | 状态 |
|------|------|---------|------|
| 共享层成为瓶颈 | 中 | 只做规则级处理，并行化 I/O | ✅ 已缓解 |
| Lane 改造破坏现有功能 | 高 | 分阶段改造，充分测试，保留开关 | ⏳ 待验证 |
| 一致性校验误报 | 中 | 初期只检测不修复，人工审核 | ⏳ 待验证 |
| 性能不达预期 | 中 | 性能测试，调优并发参数 | ⏳ 待验证 |

## 实施时间线

| 阶段 | 预计时间 | 状态 |
|------|---------|------|
| 设计文档 | 1 天 | ✅ 已完成 |
| 共享准备层 | 1 天 | ✅ 已完成 |
| 构建协调层 | 1 天 | ✅ 已完成 |
| Doc Lane 改造 | 2 天 | ⏳ 待开始 |
| KG Lane 改造 | 2 天 | ⏳ 待开始 |
| API 层整合 | 1 天 | ⏳ 待开始 |
| 测试验证 | 2 天 | ⏳ 待开始 |
| **总计** | **10 天** | **30% 完成** |

## 代码统计

| 模块 | 文件数 | 代码行数（估算） |
|------|--------|-----------------|
| 共享准备层 | 6 | ~800 行 |
| 构建协调层 | 7 | ~600 行 |
| 设计文档 | 3 | ~1000 行 |
| **总计** | **16** | **~2400 行** |

## 关键决策记录

### 决策 1：不做超级串行图

**背景**：可以把 docgen 和 KG 的所有节点塞进一张巨大的 LangGraph

**决策**：保留两条子图，只加轻量协调层

**理由**：
- 保持现有架构稳定
- 降低改造风险
- 更容易回退

### 决策 2：所有协作都是软依赖

**背景**：可以让 doc lane 强制等待 KG lane 的结果

**决策**：设置超时，等不到就降级

**理由**：
- 避免互相阻塞
- 提升鲁棒性
- 保证性能

### 决策 3：修复必须局部化

**背景**：可以全量重跑来修复缺口

**决策**：有预算上限的局部修复

**理由**：
- 控制成本
- 降低风险
- 可预测性

### 决策 4：共享层只做规则级处理

**背景**：可以在共享层调用 LLM 做深度清洗

**决策**：只做规则级处理，不调 LLM

**理由**：
- 保证速度
- 降低成本
- 避免成为瓶颈

## 总结

本次实施完成了 Digest 统一构建的核心架构设计和基础代码实现，为知识文档和知识图谱的协同构建奠定了坚实基础。

**核心成果**：
- ✅ 完整的架构设计（3 份文档）
- ✅ 共享准备层实现（6 个模块）
- ✅ 构建协调层实现（7 个模块）
- ✅ 一致性校验机制
- ✅ 可回退设计

**核心优势**：
- 消除重复劳动
- 双向增强
- 自动一致性保证
- 充分利用 assets
- 可控风险

**下一步**：
1. 改造 Doc Lane（5 个节点）
2. 改造 KG Lane（3 个节点）
3. API 层整合
4. 充分测试验证

这是一个经过深思熟虑、可控、可验证、可回退的方案，适合在生产环境中逐步推进。
