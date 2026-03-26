# 14. 数据库重构设计（v2）

## 1. 重构目标

- 删除全部 legacy 表，不兼容，不留旧债
- 合并 1:1 表（raw_file + document 合并、版本表合并等）
- 表名见名知意，全部单数 snake_case
- 每张表说清楚：是什么、存什么、在前端对应什么
- 补齐缺失的表（user、raw_file_asset）
- 兼顾本地部署（SQLite）和中心化部署（PostgreSQL）

---

## 2. 部署方案建议

### 本地部署（当前）
- DB: SQLite + sqlite-vec
- 文件: 本地 `data/` 目录
- 适合: 单用户、开发、演示

### 中心化部署（推荐 PostgreSQL + OSS）

| 方案 | DB | 向量 | 文件 | 优劣 |
|---|---|---|---|---|
| MySQL + OSS | MySQL 8 | 需额外向量库(Milvus等) | 阿里云OSS/S3 | 向量检索需要独立服务，运维复杂 |
| PostgreSQL + OSS | PostgreSQL 16 | pgvector 内置 | 阿里云OSS/S3 | 向量检索原生支持，一个DB搞定，生态好 |

**推荐 PostgreSQL + pgvector + OSS**，理由：
1. pgvector 是 PostgreSQL 原生扩展，不需要额外向量数据库
2. SQLite → PostgreSQL 迁移路径比 SQLite → MySQL 更平滑（SQLModel/SQLAlchemy 兼容性好）
3. PostgreSQL 的 JSON 操作、全文检索、CTE 都比 MySQL 强
4. 阿里云 RDS PostgreSQL 直接支持 pgvector
5. 当前代码用 SQLModel，切换只需改连接字符串 + 少量方言适配

### 代码层面需要的适配
- `chunk_embedding` 虚拟表: SQLite 用 `sqlite-vec`，PostgreSQL 用 `pgvector`
- 文件路径字段: 本地存绝对路径，中心化存 `oss://bucket/key` URI
- 新增 `settings.storage_backend` 配置项（`local` / `oss`）

---

## 3. 系统数据流

```
用户上传文件
    │
    ▼
[Ingest 引擎] 解析 PDF/DOCX → Markdown + 提取图片
    │
    ▼
raw_file (文件记录 + markdown 内容)
raw_file_asset (提取的图片资源)
    │
    ▼
[Digest 引擎 - 共享准备层] 切分 Section → 生成向量
    │
    ▼
source_chunk (切块，RAG 检索 + 图谱证据的基础单元)
chunk_embedding (向量索引)
    │
    ├──────────────────────────┐
    ▼                          ▼
[Digest - 文档生成]        [Digest - 图谱构建]
    │                          │
    ▼                          ▼
knowledge_document         knowledge_node / knowledge_edge
(知识文档章节)             (知识图谱)
    │                          │
    └────────────┬─────────────┘
                 ▼
          [Digest - 课程结构]
                 │
                 ▼
          teaching_unit → curriculum_version → 主题树 + 先修DAG
                 │
                 ▼
          [Examine 引擎] 出题组卷
                 │
                 ▼
          question_template → exam_paper → user_answer_attempt
                 │
                 ▼
          [Profile 引擎] 掌握度 + 复习调度
                 │
                 ▼
          user_knowledge_state / review_task
                 │
                 ▼
          [Interact 引擎] RAG 检索 source_chunk → LLM 对话
                 │
                 ▼
          chat_session / chat_message
```

---

## 4. 完整 1:N 关系树

```
user
  └─ 1:N subject
        │
        ├─ 1:N raw_file                          # 用户上传的原始文件（含解析后的 markdown）
        │     ├─ 1:N raw_file_asset              # 从文件中提取的图片/资源
        │     └─ 1:N source_chunk                # 文档切块（RAG + 图谱证据的基础单元）
        │           └─ 1:1 chunk_embedding       # 向量索引（虚拟表）
        │
        ├─ 1:N knowledge_document                # 生成的知识文档章节
        │
        ├─ 1:N knowledge_node                    # 知识图谱节点（概念/知识点）
        │     ├─ 1:N knowledge_alias             # 节点别名
        │     ├─ 1:N knowledge_revision          # 节点内容版本
        │     └─ 1:N knowledge_evidence          # 节点到源切块的证据链
        │
        ├─ 1:N knowledge_edge                    # 知识图谱边（节点间关系）
        │     ├─ 1:N edge_revision               # 边的版本记录
        │     └─ 1:N knowledge_evidence          # 边到源切块的证据链
        │
        ├─ 1:N teaching_unit                     # 教学单元（知识点聚合）
        │     └─ 1:N teaching_unit_membership    # 知识点归属教学单元
        │
        ├─ 1:N taxonomy_anchor                   # 分类锚点（主题树骨架，自引用树）
        │
        ├─ 1:N curriculum_version                # 课程结构版本快照
        │     ├─ 1:N curriculum_tree_node        # 主题树节点
        │     ├─ 1:N curriculum_unit_link        # 教学单元挂载到树节点
        │     └─ 1:N curriculum_dependency       # 教学单元间先修依赖
        │
        ├─ 1:N question_template                 # 题目模板
        │     └─ 1:N question_template_node_link # 题目覆盖的知识点
        │
        ├─ 1:N exam_paper                        # 试卷
        │     └─ 1:N exam_paper_item             # 试卷中的每道题（快照）
        │           └─ 1:N user_answer_attempt   # 用户作答记录
        │
        ├─ 1:N user_knowledge_state              # 用户掌握度
        │
        ├─ 1:N review_task                       # 复习任务
        │
        └─ 1:N chat_session                      # 对话会话
              └─ 1:N chat_message                # 对话消息
```

说明：
- `raw_file` 合并了原来的 `document` 表（1:1 关系，没必要分开）
- `source_chunk` 合并了原来的 `document_chunk`（直接挂在 raw_file 下）
- `knowledge_evidence` 合并了原来的 `evidence_link`（去掉多态，node 和 edge 各自有证据）
- `curriculum_version` 合并了原来的 `theme_tree_version` + `prereq_dag_version` + `curriculum_snapshot`
- `curriculum_tree_node` 就是原来的 `theme_tree_node`，名字更直观
- `curriculum_unit_link` 就是原来的 `unit_tree_membership`
- `curriculum_dependency` 就是原来的 `unit_dependency`

