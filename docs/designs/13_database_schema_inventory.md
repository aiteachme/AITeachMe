# 13. Database Schema Inventory

## 1. 文档定位

这份文档是当前数据库主设计文档。
本轮目标不是继续极限压表到 15 张，而是把业务主表稳定收口到 20 张左右，去掉明显臃肿的兼容表、修订表、挂载表、attempt 表、review task 表。

当前结论：

- `20` 张业务主表是合理上限
- `chunk_embeddings` 只算向量实现层，不算业务主表
- `theme tree / prereq dag / taxonomy anchor` 继续保留为独立主表
- `membership / revision / alias / evidence / attempt / review_task` 全部并回主表字段或 JSON

---

## 2. 当前目标主树

```text
user
  └─ 1:N subject
        ├─ 1:N raw_file
        ├─ 1:N retrieval_chunk
        ├─ 1:N knowledge_document
        ├─ 1:N knowledge_node
        │     └─ 1:N knowledge_edge
        ├─ 1:N teaching_unit
        ├─ 1:N taxonomy_anchor
        ├─ 1:N theme_tree_version
        │     └─ 1:N theme_tree_node
        ├─ 1:N prereq_dag_version
        │     └─ 1:N unit_dependency
        ├─ 1:N curriculum_version
        ├─ 1:N question_template
        ├─ 1:N exam_paper
        │     └─ 1:N exam_paper_item
        ├─ 1:N user_knowledge_state
        └─ 1:N chat_session
              └─ 1:N chat_message
```

---

## 3. 20 张业务主表

### 3.1 用户与学科

1. `user`
   顶层拥有者。保存账号基础信息、最近 IP、用户级 profile JSON。

2. `subject`
   学科工作空间根。保存学科名、描述、偏好的 digest 模式、学科级 profile JSON、settings JSON。

### 3.2 原始资料与检索

3. `raw_file`
   用户上传的原始资料。保存文件路径、Markdown 路径、解析后的 Markdown 内容、资源清单、材料画像、识别出的学科信息。

4. `retrieval_chunk`
   RAG 检索的统一切块表。直接挂在 `raw_file` 下，保存标题、层级、header path、chunk 内容、向量引用信息。

### 3.3 知识文档与图谱

5. `knowledge_document`
   digest 产出的正式知识文档。支持章节、merged 文档、版本号、模式判定、manifest、source scope。

6. `knowledge_node`
   知识图谱节点主表。保存 canonical name、summary、body markdown、aliases JSON、evidence refs JSON。

7. `knowledge_edge`
   知识图谱边主表。保存 source/target、edge type、description、evidence refs JSON。

### 3.4 教学结构

8. `teaching_unit`
   教学单元主表。是 digest / examine / profile 的共同锚点。成员节点关系并入 `member_node_refs_json`。

9. `taxonomy_anchor`
   课程锚点主表。保存主题分类锚点，供主题树构建与人工管理使用。

10. `theme_tree_version`
    主题树版本表。一个学科可以有多个版本。

11. `theme_tree_node`
    主题树节点表。保留独立节点，节点下挂的教学单元并入 `unit_refs_json`。

12. `prereq_dag_version`
    先修依赖图版本表。

13. `unit_dependency`
    教学单元之间的先修边表。因为要按 source/target 独立查询，所以继续保留。

14. `curriculum_version`
    课程发布快照主表。绑定 tree version、dag version，并保存 blueprint/tree/dependency/build context JSON。

### 3.5 出题、试卷、画像

15. `question_template`
    题模板主表。题目覆盖的知识点并入 `node_refs_json`。

16. `exam_paper`
    试卷主表。保存组卷上下文、模式、总分、得分、状态。

17. `exam_paper_item`
    试卷题目快照表。直接承载用户答案、判卷结果、错误原因、反馈文本。

18. `user_knowledge_state`
    学习状态主表。保存掌握度、稳定度、遗忘时间、复习调度字段。`review_task` 已并回这里。

### 3.6 聊天

19. `chat_session`
    聊天会话元信息表。

20. `chat_message`
    聊天消息表。引用上下文并入 `contexts_json`，额外元数据并入 `meta_json`。

---

## 4. 被移除并收敛的表

下面这些表不再进入目标态：

- `raw_file_asset`
  并入 `raw_file.asset_manifest_json`

- `document`
  语义并入 `raw_file`

- `document_chunk`
  重命名并收敛为 `retrieval_chunk`

- `chunk_embedding`
  只保留物理向量表 `chunk_embeddings`，不再作为业务主表

- `knowledge_alias`
  并入 `knowledge_node.aliases_json`

- `knowledge_revision`
  并入 `knowledge_node.summary/body_markdown`

- `edge_revision`
  并入 `knowledge_edge.description`

- `evidence_link`
  并入 `knowledge_node.evidence_refs_json` 与 `knowledge_edge.evidence_refs_json`

- `teaching_unit_revision`
  并入 `teaching_unit.title/summary/learning_objectives_json`

- `teaching_unit_membership`
  并入 `teaching_unit.member_node_refs_json`

- `unit_tree_membership`
  并入 `theme_tree_node.unit_refs_json`

- `question_template_node_link`
  并入 `question_template.node_refs_json`

- `user_answer_attempt`
  并入 `exam_paper_item`

- `review_task`
  并入 `user_knowledge_state`

---

## 5. 当前关键字段约定

### 5.1 Profile 分层

- `user.profile_json`
  用户级稳定画像

- `subject.profile_json`
  学科级画像，用于 digest/exam/interact 偏好

- `user_knowledge_state`
  细粒度掌握状态

### 5.2 Digest 模式判定

`digest_mode` 的判断主要结合三部分：

- 学科名与学科描述
- 上传资料自动识别结果
- 用户上传时附带的提示词

模式不是完全两套结构，只是：

- 主流程一致
- 提示词不同
- 压缩深度不同
- 章节组织重点不同

### 5.3 版本语义

保留版本语义的表只有这些：

- `knowledge_document`
- `theme_tree_version`
- `prereq_dag_version`
- `curriculum_version`

其余局部修订信息不再拆独立表。

---

## 6. 为什么不是 15 张

这轮没有继续压到 15 张，原因很明确：

- `taxonomy_anchor` 需要独立管理，不适合直接揉进 JSON
- `theme_tree_version + theme_tree_node` 需要独立查询、分页和展示
- `prereq_dag_version + unit_dependency` 需要按边查询和更新

如果强行继续压：

- 代码复杂度会上升
- 主题树和先修图的查询会变差
- 后面知识总结页、图谱 UI、试卷组装都会被拖累

所以当前以 20 张业务主表为稳定基线。

---

## 7. 当前实现边界

当前代码实现已经按这个方向收口：

- 数据库白名单建表只创建这 20 张业务主表
- 聊天、考试、画像链路不再依赖 `attempt/review_task`
- 图谱 alias/evidence/revision 已改为主表字段或 JSON
- 教学单元成员关系、主题树单元挂载关系改为 JSON 挂载

向量层仍会创建这些物理表：

- `chunk_embeddings`
- sqlite-vec 的内部辅助表

这些不算业务主表。

---

## 8. 一句话结论

当前数据库目标态不是“继续拆”，而是：

- 主表控制在 20 张左右
- 真正有独立查询价值的结构表保留
- 其余 support 表尽量并回主表字段或 JSON
- 后续功能扩展优先加字段和 JSON，只有出现真实高频查询需求时才再拆表
