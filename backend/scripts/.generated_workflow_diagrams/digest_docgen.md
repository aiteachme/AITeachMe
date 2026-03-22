# Digest DocGen Workflow

当前知识文档工作流已经去 `job_id` 化。

外部接口只有：

- `POST /api/v1/subjects/{subject}/knowledge/build`
- `POST /api/v1/subjects/{subject}/knowledge/docs`

内部用 subject 级锁、staging 目录和 manifest 管理构建与发布。

```mermaid
flowchart TD
    A["POST /knowledge/build"] --> B{"创建 .build.lock"}
    B -- "已存在" --> C["409 BUILD_IN_PROGRESS"]
    B -- "成功" --> D["记录 requested_at"]
    D --> E["load_files"]
    E --> F["cleanse"]
    F --> G["outline_map"]
    G --> H["outline_reduce"]
    H --> I["draft_chapter x N"]
    I --> J["review_chapter x N"]
    J --> K["extract_metadata x N"]
    K --> L["写入 _building/chapter_XX_*.md"]
    L --> M["生成 _building/merged_knowledge_base.md"]
    M --> N["覆盖发布目录 knowledge_docs/"]
    N --> O["写入 manifest.json"]
    O --> P["重建 KnowledgeDoc published 记录"]
    P --> Q["删除 .build.lock"]

    R["前端本地进度条"] --> S["POST /knowledge/docs"]
    S --> T["读取 merged_knowledge_base.md + manifest.json"]
    T --> U{"updated_at >= requested_at ?"}
    U -- "是" --> V["前端补到 100%"]
    U -- "否" --> S
```
