> 2026-04-16 当前仓库说明：本文保留 Digest 历史设计上下文。当前真实代码边界以 `backend/app/workflows/digest/README.md`、`backend/app/workflows/STRUCTURE.md` 与 `docs/designs/05_digest_engine.md` 为准；旧 `services/`、`docgen/internal/` 等路径不再作为源码入口。

下面我按“**知识图谱型增量构建**”来给你做一版完整设计，并且重点回答第二个核心问题：

> **如何在知识图谱的基础上稳定地产生一个“课程树”**，而不是每次都生成一份漂浮不定的目录。

我会尽量按你一贯偏好的工程化方式来写：**目标 → 总体架构 → 领域模型 → 增量更新流程 → 图谱构建算法 → 课程树派生算法 → 冲突与修订 → API / 数据表 → 推荐落地路径**。

---

# 1. 目标重述

你要的不是一个普通 digest，而是一个长期演化的 **Course Knowledge Compiler**。

它要满足：

## 1.1 持续增量

每次上传新文档后，不是“重新总结全部”，而是：

* 只处理新增/变更文档
* 只更新受影响的知识节点与关系
* 只重算受影响的课程树局部

## 1.2 图谱化表达

知识不能只是平铺卡片，而要支持：

* 概念依赖
* 上下位关系
* 部分-整体关系
* 定义 / 定理 / 方法 / 例题 / 易错点之间的联系
* 不同教材、不同表述之间的映射与冲突

## 1.3 树化展示

虽然底层是真正的图谱，但前台/产品层仍然需要：

* 课程目录树
* 章节页
* 主题页
* 可浏览、可折叠、可检索

也就是说：

> **底层是图，展示层是树。**

## 1.4 可追溯

每一个知识点、关系、目录节点，都应该能回答：

* 这条知识从哪篇文档来的？
* 由哪些片段支撑？
* 是哪个版本的文档引入或修订了它？
* 为什么被放在这个课程树节点下？

---

# 2. 总体架构

我建议拆成 6 层。

---

## 2.1 Source Layer：文档源层

管理原始材料：

* PDF
* PPT
* 讲义
* 笔记
* 试题
* 课程大纲
* 教材章节

产物：

* Document
* DocumentVersion
* Chunk
* StructuralSpan（标题、章、节、页、公式块、题目块等）

---

## 2.2 Extraction Layer：信息抽取层

从 chunk 里抽取图谱候选元素：

* 概念
* 定义
* 定理
* 公式
* 方法
* 例题
* 习题类型
* 易错点
* 前置知识
* 所属主题候选
* 关系候选

产物：

* CandidateNode
* CandidateEdge
* CandidateTaxonomyHint
* EvidenceCandidate

---

## 2.3 Reconciliation Layer：对齐归并层

把候选元素与已有图谱做匹配：

* 是已有概念的别名？
* 是已有知识节点的新证据？
* 是已有关系的新支持？
* 还是全新的节点/关系？

产物：

* NodeMergeDecision
* EdgeMergeDecision
* ConflictRecord
* NewNodePlan
* NewEdgePlan

---

## 2.4 Graph Layer：知识图谱层

维护课程底层真相：

* 节点
* 边
* 修订
* 证据
* 版本
* 置信度
* 生效状态

产物：

* KnowledgeNode
* KnowledgeEdge
* KnowledgeRevision
* EvidenceLink
* TaxonomyAnchor

---

## 2.5 Tree Derivation Layer：课程树派生层

从图谱中派生出 **稳定的课程树**：

* 基于 taxonomy 类边与主题锚点生成树
* 基于先验课程大纲、教材目录、聚类结果做融合
* 保证树结构稳定，不因一次文档上传乱跳

产物：

* CourseTree
* TreeNode
* TreeMembership
* TreeVersion

---

## 2.6 Publishing Layer：产品发布层

为前台提供：

* 课程总览
* 目录树浏览
* 主题页
* 知识点详情页
* 学习路径
* 章节摘要
* 复习提纲

---

# 3. 为什么底层一定要“图”，上层才做“树”

因为课程知识天然不是树，而是图。

例如：

“导数”同时具有：

* 是“微积分”下的核心概念
* 依赖“极限”
* 推导出“微分”
* 在“运动学”中用于速度
* 在“优化”中用于最值

如果你硬把底层建成树，会出现两个问题：

## 3.1 多重归属难以表达

同一个知识点同时属于多个主题。

## 3.2 依赖关系和目录关系混淆

目录关系是“属于哪一章”，依赖关系是“先学什么”。
这两个不是一回事。

所以必须分离：

* **Graph = 真正知识结构**
* **Tree = 某个视角下的组织结构**

---

# 4. 领域模型设计

下面是核心模型。

---

## 4.1 节点类型（Node Types）

建议至少有这些类型：

### Concept

抽象概念
例：

* 极限
* 导数
* 栈
* 动态规划
* 马尔可夫链

### Definition

正式定义
例：

* 导数的极限定义
* 栈的定义

### Theorem / Proposition

定理、命题、性质
例：

* 中值定理
* 链式法则

### Formula

公式
例：

* 导数定义公式
* 贝叶斯公式

### Method

方法 / 算法 / 解题套路
例：

* 换元积分法
* 快速排序

### Example

例题 / 例子
例：

* 求 x² 的导数
* 栈实现括号匹配

### ExerciseType

题型
例：

* 求极限题
* 导数应用题
* 遍历二叉树题

### Misconception

易错点 / 误区
例：

* 极限存在不代表函数值存在
* DFS 不等于递归本身

### Topic

主题节点，偏组织层
例：

* 函数与极限
* 导数与微分
* 图论基础

### SyllabusUnit

来自课程大纲或教材的结构节点
例：

* 第一章 函数与极限
* 1.2 极限运算法则

这个类型很重要，因为后面课程树不是纯自动聚类长出来的，往往需要 **SyllabusUnit / Topic** 作为锚点。

---

## 4.2 边类型（Edge Types）

建议分四大类，不要混。

---

### A. 语义结构边

#### `is_a`

上位-下位
例：

* 单侧极限 is_a 极限概念的子类

#### `part_of`

部分-整体
例：

* 链式法则 part_of 求导法则体系

#### `same_as`

同义 / 等价节点
例：

* depth-first search same_as 深度优先搜索

#### `alias_of`

别名关系
例：

* 导函数 alias_of 导数函数

---

### B. 学习依赖边

#### `prerequisite_of`

前置知识
例：

* 极限 prerequisite_of 导数

#### `uses`

使用到
例：

* 牛顿法 uses 导数

#### `derived_from`

推导自
例：

* 微分 derived_from 导数概念

---

### C. 教学组织边

#### `belongs_to_topic`

属于主题
例：

* 链式法则 belongs_to_topic 导数与微分

#### `belongs_to_syllabus_unit`

属于课程单元
例：

* 极限定义 belongs_to_syllabus_unit 第一章/第二节

#### `next_topic`

主题顺序
例：

* 极限 → 导数 → 积分

---

### D. 证据与说明边

#### `defined_by`

概念由定义节点定义
例：

* 导数 defined_by 导数定义

#### `explained_by`

概念由某解释节点说明

#### `illustrated_by`

概念由例题说明
例：

* 栈 illustrated_by 括号匹配例题

#### `tested_by`

知识点被某题型考查
例：

* 导数 tested_by 导数应用题

#### `conflicts_with`

冲突关系
例：

* 某教材表述 conflicts_with 另一教材表述

---

# 5. 数据实体设计

---

## 5.1 KnowledgeNode

```text
KnowledgeNode
- id
- course_id
- node_type
- canonical_name
- normalized_name
- aliases_json
- canonical_summary
- canonical_body
- difficulty_level
- granularity_level
- language
- status (active / deprecated / merged / pending_review)
- confidence
- created_at
- updated_at
- current_revision_id
```

说明：

* `canonical_name`：当前标准名称
* `granularity_level`：控制太细/太粗的问题
* `confidence`：系统对节点质量的总体信心

---

## 5.2 KnowledgeRevision

```text
KnowledgeRevision
- id
- node_id
- revision_no
- title
- content
- revision_reason (new_evidence / merge / split / human_edit / conflict_resolution)
- generated_by_job_id
- is_current
- created_at
```

---

## 5.3 KnowledgeEdge

```text
KnowledgeEdge
- id
- course_id
- source_node_id
- target_node_id
- edge_type
- directionality
- weight
- confidence
- status (active / deprecated / pending_review)
- current_revision_id
- created_at
- updated_at
```

---

## 5.4 EdgeRevision

```text
EdgeRevision
- id
- edge_id
- revision_no
- description
- weight
- confidence
- revision_reason
- generated_by_job_id
- is_current
- created_at
```

---

## 5.5 EvidenceLink

```text
EvidenceLink
- id
- course_id
- entity_type (node / edge / tree_membership / tree_node_summary)
- entity_id
- document_id
- document_version_id
- chunk_id
- page_from
- page_to
- quote_text
- evidence_role (supports / elaborates / contradicts / exemplifies / taxonomy_hint)
- confidence
- created_at
```

这张表非常关键。
节点、边、树归属都要能挂证据。

---

## 5.6 TaxonomyAnchor

用于课程树锚点。

```text
TaxonomyAnchor
- id
- course_id
- anchor_type (syllabus / textbook_toc / teacher_defined / graph_discovered)
- title
- normalized_title
- parent_anchor_id
- order_index
- confidence
- status
```

它不是知识图谱节点本身，但与图谱节点关联，帮助形成树。

---

## 5.7 TreeNode / TreeVersion

```text
CourseTreeVersion
- id
- course_id
- version_no
- derivation_strategy
- status
- created_at

CourseTreeNode
- id
- tree_version_id
- anchor_id
- parent_tree_node_id
- title
- node_type (chapter / section / topic / concept_bucket)
- order_index
- derived_confidence
- summary
```

---

## 5.8 TreeMembership

```text
TreeMembership
- id
- tree_version_id
- tree_node_id
- knowledge_node_id
- membership_role (primary / secondary / cross_link)
- score
- reason_code
```

一个知识点可以有：

* 一个主归属 `primary`
* 多个次归属 `secondary`
* 若干交叉链接 `cross_link`

这样树结构稳定，而图的多归属能力也保留。

---

# 6. 增量构建流程

每次上传新文档后，建议走下面 9 步。

---

## Step 1. 文档预处理

做：

* OCR / 文本抽取
* 目录识别
* 标题层级识别
* chunk 切分
* 公式块 / 例题块 / 定义块识别
* 文档类型识别（教材、讲义、习题、笔记）

产物：

* `Chunk`
* `StructuralSpan`
* `DocumentOutline`

---

## Step 2. 候选节点抽取

从 chunk 中抽取候选知识单元。

抽取结果不是最终节点，而是：

```text
CandidateNode
- name
- node_type
- local_summary
- structural_context
- lexical_features
- embedding
- taxonomy_hint
- evidence_chunk_id
```

例如某个 chunk 抽出：

* 候选 Concept：导数
* 候选 Definition：导数定义
* 候选 Formula：f'(x)=...
* 候选 TopicHint：导数与微分

---

## Step 3. 候选边抽取

同一 chunk 或相邻 chunk 内识别关系。

例如：

* “导数以极限为基础定义”

  * 极限 prerequisite_of 导数
* “链式法则是求导法则之一”

  * 链式法则 part_of 求导法则
* “例 2-3 利用链式法则求导”

  * 链式法则 illustrated_by 例2-3

---

## Step 4. 节点对齐（Entity Resolution）

这是最核心的。

对每个 CandidateNode 判断：

### 4.1 是否匹配已有节点

通过：

* 名称规范化匹配
* 别名词典
* embedding 相似度
* 局部上下文相似度
* LLM 判别“是否同一知识点”
* 类型兼容性检查

输出：

* exact_match
* probable_match
* no_match
* ambiguous_match

---

## Step 5. 边对齐（Relation Resolution）

对于 CandidateEdge：

* 如果图中已有同类型边，增加证据或提高权重
* 如果冲突，记录 conflict
* 如果新发现，创建新边

---

## Step 6. 版本化更新

对于节点和边做 revision，而不是暴力覆盖。

### 节点更新策略

#### 追加证据

只是新的教材再次讲到了该知识
=> 增加 `EvidenceLink`

#### 局部修订

新教材给出更完整定义
=> 生成新的 `KnowledgeRevision`

#### 拆分

原来一个节点太粗，现在发现应拆成多个
=> split

#### 合并

原来有两个重复节点
=> merge

---

## Step 7. 局部影响分析

根据变更节点/边，计算受影响的局部子图。

例如新增“单侧极限”后可能影响：

* 极限主题
* 极限定义摘要
* 导数前置知识图
* 第一章课程树摘要

不要全量重算整科。

---

## Step 8. 课程树局部派生更新

只对受影响主题子树做重算：

* 新节点挂哪里
* 某个主题下是否新增子主题
* 某个 TreeMembership 是否改变

---

## Step 9. 发布产物更新

更新：

* 课程目录页
* 主题摘要
* 知识点详情页
* 搜索索引
* 向量索引
* 学习路径候选

---

# 7. 核心难点一：知识图谱如何稳定增量更新

关键不是“抽出东西”，而是 **不把原系统弄乱**。

我建议三套机制。

---

## 7.1 节点身份稳定机制

每个知识节点要有 **稳定身份**，不能每次上传都重新造一个。

可用三层 identity：

### Layer 1：Canonical Identity

由管理员/系统确认的正式身份

### Layer 2：Normalized Signature

根据标准化名称 + 类型 + 上下文构成的签名

### Layer 3：Evidence Cluster

由多个证据片段聚成的簇

只要新候选落入已有 cluster，就不要新建节点。

---

## 7.2 合并 / 拆分机制

知识点粒度会变化，所以必须允许：

### Merge

“深度优先搜索”和“DFS”原本两个节点，后面发现应合并

### Split

“极限”节点太粗，拆成：

* 数列极限
* 函数极限
* 左极限
* 右极限

所以系统必须支持：

* merge_map
* split_from / split_to
* 迁移 evidence
* 迁移 tree membership

---

## 7.3 冲突机制

教材之间表述可能冲突。

例如：

* 某定义表述差异
* 某术语命名不同
* 某分类方式不同

不要直接覆盖，应当：

* 保留 canonical 版本
* 冲突版本作为 alternative revision
* 标注来源文档
* 在前台显示“不同资料存在不同表述”

---

# 8. 核心难点二：如何从图谱得到一棵课程树

这是你问的重点。

## 8.1 先讲结论

**不能直接从全图自动抽一棵树。**

因为图有：

* 多归属
* 环
* 依赖边
* 交叉解释
* 示例边

如果你直接抽树，结果会非常不稳定。

所以必须先做 **树派生约束**：

> 图谱中只有一部分边和一部分锚点参与“树化”。

---

# 9. 课程树派生的核心思想

我建议用：

## **“Anchor-based Taxonomy Derivation”**

即：
先建立一组 **taxonomy anchors（分类锚点）**，再把知识节点挂到这些锚点下，最后形成树。

---

## 9.1 什么是 Anchor

Anchor 是用于树组织的节点，不等于所有知识节点。

来源可以是：

### A. 教师/管理员定义的大纲

最稳定
例如：

* 第一章 函数与极限
* 第二章 导数与微分

### B. 教材/讲义目录抽取

例如从 PDF 目录识别：

* 1.1 函数
* 1.2 极限
* 1.3 连续

### C. 图谱发现的高中心主题

从图中自动发现：

* 极限主题簇
* 导数主题簇
* 图论主题簇

这些可以作为候选锚点。

---

## 9.2 树派生只使用“taxonomy-eligible edges”

不是所有边都用于树化。
只允许这些边参与形成树：

* `belongs_to_topic`
* `belongs_to_syllabus_unit`
* `is_a`（谨慎）
* `part_of`（谨慎）
* `next_topic`（仅排序参考，不用于父子）
* anchor parent-child 关系

而以下边绝不能直接参与树化：

* `prerequisite_of`
* `uses`
* `illustrated_by`
* `tested_by`
* `conflicts_with`

---

# 10. 课程树派生算法设计

---

## 10.1 输入

* 当前知识图谱 G
* 一组 TaxonomyAnchors
* Anchor parent-child 结构
* 每个知识节点到 anchor 的候选关联分数
* 人工规则 / 课程大纲优先级
* 上一版本课程树 T_prev

---

## 10.2 输出

* 新的课程树版本 T_new
* 每个知识节点的主归属与次归属
* 每个树节点摘要

---

## 10.3 派生分 5 步

---

### Step A. 生成 Anchor Skeleton

先生成一棵只包含 anchor 的骨架树。

优先级：

1. teacher_defined
2. syllabus
3. textbook_toc
4. graph_discovered

规则：

* 如果 teacher_defined 存在，就以它为主骨架
* graph_discovered 只能补充，不轻易改动主骨架

这样做的好处是：
**树稳定，不会因为一次上传乱改章节结构。**

---

### Step B. 为每个知识节点计算挂载分数

每个 knowledge node 对每个 anchor 计算一个 `membership_score`。

可以综合：

#### 1. 文本相似度

知识节点文本 vs anchor 标题 / 摘要

#### 2. 结构上下文

节点来源 chunk 所处的文档目录位置

#### 3. 图邻域投票

一个节点的邻居大多属于哪个主题，它也更可能属于那个主题

#### 4. 教材目录提示

如果文档中该段位于“1.2 极限”，那这是强信号

#### 5. 先验规则

例如：

* Definition 通常挂到其对应 Concept 所在主题
* Example 通常挂到被说明的知识点所在主题

公式上可以写成：

```text
membership_score(node, anchor) =
  w1 * semantic_similarity
+ w2 * structural_hint_score
+ w3 * graph_neighbor_vote
+ w4 * syllabus_alignment_score
+ w5 * historical_stability_bonus
```

其中 `historical_stability_bonus` 非常重要。
否则节点会来回漂。

---

### Step C. 确定主归属 Primary Membership

每个节点只选一个主归属，其他作为次归属。

规则建议：

* 分数最高且超过阈值 → 主归属
* 若前两名差距太小 → 标记待审查或保留原归属
* 若旧树已有归属且新分数提升不明显 → 保持旧归属

这是保证树稳定的关键。

---

### Step D. 形成 Topic Buckets

在每个 anchor 下，把知识节点再按类型和密度组织：

* 概念
* 定义
* 方法
* 公式
* 例题
* 易错点

必要时自动形成子 topic bucket，例如：

* 极限概念
* 极限运算
* 极限性质

但这一步必须受控，不能无限裂变。

---

### Step E. 生成 TreeNode Summary

每个树节点 summary 来源于：

* 该 anchor 下的核心概念节点
* 其定义节点
* 高频关系
* 前置知识与后续主题关系

summary 也是派生产物，不是主数据。

---

# 11. 如何保证课程树不是“漂移树”

这非常关键。

我建议 6 条稳定性原则。

---

## 11.1 主骨架优先固定

如果已经有教师定义大纲，就不要轻易改 anchor 结构。

---

## 11.2 新节点先挂“待归类”而不是乱插

如果分数不够高，不要强行挂到某个主题。
先放：

* 待归类
* 交叉主题
* 临时 topic

---

## 11.3 节点迁移要有阈值

不要因为一次分数微增就把节点移树。

例如：

* 原 anchor 分数 0.76
* 新 anchor 分数 0.79

这种不迁移。
必须超过明显阈值才迁移，比如：

* 新分数高于旧分数 0.12 以上
* 且新 anchor 有更多结构证据支持

---

## 11.4 主归属唯一，次归属多值

树上只有一个主位置，但详情页可展示交叉主题。

---

## 11.5 局部变更，局部重算

只重算受影响子树。

---

## 11.6 树版本化

不要直接覆盖旧树。
每次派生出：

* `CourseTreeVersion`

这样你可以：

* 回滚
* 比较变更
* 展示“本次新增了哪些知识点”

---

# 12. 图谱到课程树的一个具体例子

以“高等数学”为例。

---

## 图谱里有这些节点

### Topic / Anchor

* 第一章 函数与极限
* 第二章 导数与微分

### Concept

* 函数
* 极限
* 连续
* 导数
* 微分

### Definition

* 极限定义
* 导数定义

### Theorem

* 极限四则运算
* 夹逼定理
* 链式法则

### Example

* 求 (\lim_{x \to 0} \sin x / x)
* 求 (x^2) 的导数

### Edges

* 极限 prerequisite_of 导数
* 导数 prerequisite_of 微分
* 夹逼定理 belongs_to_topic 函数与极限
* 链式法则 belongs_to_topic 导数与微分
* 导数 defined_by 导数定义
* 链式法则 illustrated_by 求复合函数导数例题

---

## 派生成树后

* 高等数学

  * 第一章 函数与极限

    * 函数
    * 极限

      * 极限定义
      * 极限四则运算
      * 夹逼定理
      * 极限例题
    * 连续
  * 第二章 导数与微分

    * 导数

      * 导数定义
      * 求导法则
      * 链式法则
      * 导数例题
    * 微分

注意：

* `prerequisite_of` 没直接形成树父子
* 它只作为“学习路径”或“前置关系”显示
* 树父子更多来自 `belongs_to_topic` + anchor skeleton + controlled buckets

---

# 13. 目录化的三层视图

你其实不要只做“一棵树”，最好做三种视图。

---

## 13.1 Syllabus Tree

按课程大纲 / 教材章节
适合浏览和教学

---

## 13.2 Concept Tree

按概念上下位
例如：

* 数据结构

  * 线性结构

    * 栈
    * 队列
  * 树结构

    * 二叉树
    * 平衡树

这个树更多来自 `is_a` / `part_of`

---

## 13.3 Learning Path Graph

按前置依赖
例如：

* 极限 → 连续 → 导数 → 微分 → 积分

这不是树，而是 DAG。
前台可以展示成“学习路线”。

所以最好的产品不是只显示一个目录，而是：

* 左侧：课程树
* 详情页：概念关系图 / 学习依赖图 / 证据来源

---

# 14. 推荐的增量算法策略

我建议做成三层更新模式。

---

## Mode 1：Fast Increment

每次上传都走

* 新节点抽取
* 匹配已有节点
* 增加 evidence
* 局部挂树
* 局部更新 summary

---

## Mode 2：Local Reconcile

当某个主题变更较多时触发

* 重新聚合该主题下的概念
* 重新分配二级 buckets
* 重写该子树摘要

---

## Mode 3：Global Taxonomy Maintenance

低频任务

* 合并重复主题
* 发现多余 anchor
* 调整 graph_discovered anchors
* 优化树骨架
* 发现长期待归类节点

---

# 15. API 设计建议

---

## 15.1 上传文档并触发增量更新

`POST /courses/{course_id}/documents:ingest`

返回：

* document_id
* digest_job_id

---

## 15.2 查看 digest job

`GET /courses/{course_id}/digest-jobs/{job_id}`

返回：

* 新增节点数
* 更新节点数
* 新增边数
* 受影响子树
* 待归类节点数

---

## 15.3 获取知识图谱节点

`GET /courses/{course_id}/knowledge/nodes/{node_id}`

返回：

* canonical 内容
* revisions
* evidence
* related nodes
* primary tree membership
* prerequisite graph

---

## 15.4 获取课程树

`GET /courses/{course_id}/trees/current`

---

## 15.5 获取某树节点详情

`GET /courses/{course_id}/trees/current/nodes/{tree_node_id}`

返回：

* summary
* child nodes
* member knowledge nodes
* examples
* misconceptions
* prerequisites
* sources

---

## 15.6 人工确认挂载/合并

`POST /courses/{course_id}/taxonomy/review-actions`

动作：

* merge_nodes
* split_node
* reassign_membership
* approve_anchor
* reject_anchor

---

# 16. 工程模块拆分建议

如果按你熟悉的 DDD/Hexagonal 思路，我建议模块这样拆。

---

## domain/knowledge_graph

* entities/

  * knowledge_node.py
  * knowledge_edge.py
  * evidence_link.py
  * taxonomy_anchor.py
  * tree_version.py
* value_objects/

  * node_type.py
  * edge_type.py
  * membership_role.py
* services/

  * entity_resolution_service.py
  * relation_resolution_service.py
  * taxonomy_derivation_service.py
  * impact_analysis_service.py

---

## application/digest

* usecases/

  * ingest_document_and_update_graph.py
  * reconcile_candidate_nodes.py
  * rebuild_course_subtree.py
  * publish_course_tree_version.py

---

## infrastructure/llm

* node_extractor.py
* edge_extractor.py
* taxonomy_hint_extractor.py
* merge_decider.py

---

## infrastructure/indexing

* embedding_index.py
* graph_store.py
* search_index.py

---

## interfaces/api

* courses_documents_api.py
* knowledge_graph_api.py
* course_tree_api.py
* taxonomy_review_api.py

---

# 17. 我建议你先做的 MVP 范围

不要一开始就做全自动完美图谱。
我建议第一版控制在：

## 必做

* KnowledgeNode
* KnowledgeEdge
* EvidenceLink
* TaxonomyAnchor
* CourseTreeVersion
* TreeMembership
* 增量 ingest job
* 局部子树更新

## 边类型只先做

* belongs_to_topic
* prerequisite_of
* defined_by
* illustrated_by
* part_of

## 节点类型只先做

* Topic
* Concept
* Definition
* Method
* Example

## 树派生只先做

* teacher_defined / syllabus anchors
* primary membership
* 待归类池
* tree summary

这样工程量可控，但已经足够强了。

---

# 18. 最终推荐的核心方案

如果我把整套方案压缩成一句话，就是：

> **把 digest 变成一个“证据驱动、版本化、可增量对齐的知识图谱系统”，然后基于 taxonomy anchors 派生出稳定的课程树。**

它的关键点不是“让 LLM 生成一棵树”，而是：

1. **先把知识作为图谱沉淀下来**
2. **再用受控的 taxonomy 规则把图谱映射成树**
3. **树版本化、局部更新、主归属稳定、次归属保留**
4. **所有节点/边/挂载都有 evidence 可追溯**

---

# 19. 我对你这个系统的最核心建议

你现在最容易犯的错是：

## 错误路线

* 上传文档
* LLM 直接生成“本课程的新目录与总结”
* 覆盖旧内容

这会非常不稳定。

## 正确路线

* 上传文档
* 抽取候选知识节点与边
* 与已有图谱做对齐归并
* 更新 evidence / revisions
* 基于稳定锚点派生局部课程树
* 生成局部 summary

这样才是真正能长期演化的 digest。

---

下一步我可以直接继续给你写成更工程化的一版：
**数据库表结构 + Python 领域模型 + 增量构建时序图 + “图谱生成课程树”的伪代码设计**。
