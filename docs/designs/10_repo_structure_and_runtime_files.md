# 10. 仓库结构与运行时文件

## 1. 文档定位

本文档只回答两件事：

- 现在应该按什么顺序读仓库
- 运行时文件到底怎么落盘

数据库表职责请看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。

---

## 2. 推荐阅读顺序

后端主顺序：

`api → services → workflows → shared → utils`（辅助层：`repositories` / `models` / `schemas` / `teaching`）

原因：

- `api` 告诉你对外资源长什么样
- `services` 告诉你请求怎么被收敛成用例
- `workflows` 告诉你五大引擎真实怎么跑
- `shared` 告诉你规范基础设施和通用底座怎么封装
- `utils` 告诉你运行时路径与纯工具函数怎么组织
- `repositories / models` 告诉你数据最终怎么落
- `teaching` 当前主要是兼容层，阅读优先级低于 `shared`

---

## 3. 顶层目录

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 页面、组件、前端 API 调用 |
| `backend/` | FastAPI、workflow、repository、model、运行时数据根 |
| `docs/` | 设计文档 |
| `backend/scripts/` | 工具脚本与辅助脚本 |
| `backend/skills/` | 教学技能定义 |
| `backend/tools/` | 工具配置 YAML |

---

## 4. 后端核心目录

`backend/app/` 当前核心目录为：

| 目录 | 作用 |
| --- | --- |
| `api/` | HTTP 资源入口 |
| `services/` | 用例入口与结果封装 |
| `workflows/` | 五大引擎编排中心 |
| `repositories/` | 查询与持久化帮助 |
| `models/` | 业务表模型 |
| `schemas/` | API 与 workflow 输入输出模型 |
| `shared/` | 规范基础层，含 `shared/kernel` 与 `shared/infra` |
| `teaching/` | 兼容层 / 迁移过渡层，不再作为新设计主入口 |
| `utils/` | 纯工具函数与运行时路径 helper |

### 4.1 分层理解与依赖口径

当前最重要的口径不是“机械记忆某个旧分层图”，而是记住下面几条：

- 新代码优先从 `app.shared.*` 导入规范基础能力
- `app.teaching.*` 视为兼容层，不再反向定义主设计
- `api` 负责资源入口，`services` 负责用例编排，`workflows` 负责复杂流程落地
- `repositories / models / schemas / utils` 都是支撑层，不应抢占业务主编排职责
- `utils/` 应保持纯工具属性，不依赖 `services/` 或 `workflows/`

其中最需要优先读的是 `workflows/`，因为复杂主链路已经正式迁到这里。

---

## 5. 当前数据根目录

默认数据根目录来自 `backend/app/shared/infra/runtime_paths.py` 的 `get_runtime_data_dir()`。

在当前仓库的常见落点是：

`backend/data/`

其中：

- `backend/data/aiteachme.db` 是主 SQLite 数据库
- 每个 `subject` 都有自己的运行时目录
- 用户级运行时画像与学习档案也默认落在这个 runtime root 下

这里要特别注意：

- runtime root 的真相源是 `app.shared.infra.runtime_paths`
- 具体业务路径的真相源是 `app.utils.path_helpers`

如果未来要迁到 `.atm/`，应通过 runtime root 配置迁移完成，而不是在各业务模块里硬编码新根目录。

---

## 6. Subject 目录真实布局

当前真实目录由 `backend/app/utils/path_helpers.py` 定义：

```text
backend/data/<subject>/
├─ raw_files/
├─ raw_markdowns/
├─ assets/
│  └─ <file_id>/
├─ exam/
├─ knowledge_markdowns/
│  └─ _build/
├─ temp/
└─ debug/
```

目录职责：

| 目录 | 作用 |
| --- | --- |
| `raw_files/` | 原始上传文件 |
| `raw_markdowns/` | ingest 产出的材料层 Markdown |
| `assets/<file_id>/` | 单文件图片与附件资产 |
| `exam/` | 考试卷导出产物（`md/tex/pdf`） |
| `knowledge_markdowns/` | 已发布知识文档 |
| `knowledge_markdowns/_build/` | 知识文档 staging 与中间产物 |
| `temp/` | 临时文件 |
| `debug/` | workflow 调试快照 |

---

## 7. 主要路径 helper

当前最重要的 helper 位于 `backend/app/utils/path_helpers.py`：

- `build_raw_dir()`
- `build_raw_file_path()`
- `build_raw_markdown_dir()`
- `build_raw_markdown_path()`
- `build_asset_dir()`
- `build_exam_dir()`
- `build_knowledge_markdown_dir()`
- `build_knowledge_doc_path()`
- `build_knowledge_manifest_path()`

这些 helper 才是运行时路径真相，文档和代码都应以它们为准。

补充说明：

- runtime root 本身由 `app.shared.infra.runtime_paths.get_runtime_data_dir()` 决定
- `app.utils.path_helpers` 在这个 root 之上继续拼接 subject / 文件级路径
- 旧的 `services/upload_support.py` 已删除，新代码必须从 `app.utils.path_helpers` 导入

---

## 8. 当前正式产物

### 8.1 Ingest 之后

- `raw_files/<raw_file_id>.<ext>`
- `raw_markdowns/<raw_file_id>.md`
- `assets/<raw_file_id>/*`

### 8.2 Digest Docs 发布之后

- `knowledge_markdowns/chapter_XX_*.md`
- `knowledge_markdowns/merged_knowledge_base.md`
- `knowledge_markdowns/manifest.json`
- `knowledge_markdowns/.build.lock`
- `knowledge_markdowns/build_status.json`

### 8.3 中间与调试产物

- `knowledge_markdowns/_build/*`
- `exam/*`
- `temp/*`
- `debug/*`

### 8.4 用户级 / 学科级运行时画像文件

当前已经存在的运行时兼容文件：

- `backend/data/users/<user_id>/LEARNER.md`

下一阶段推荐归一后的布局：

```text
backend/data/users/<user_id>/
└─ profile/
   ├─ LEARNING_PROFILE.md
   ├─ LEARNER.md
   └─ subjects/
      └─ <subject>/
         └─ LEARNING_SUBJECT_PROFILE.md
```

说明：

- 结构化真相仍在数据库，不在 markdown 文件里
- `LEARNER.md` 保留兼容语义，继续服务旧 prompt / 旧工具 / 旧脚本
- `LEARNING_PROFILE.md` 负责跨学科、偏稳定的用户学习画像
- `LEARNING_SUBJECT_PROFILE.md` 负责单学科、偏动态的学习状态与教学建议
- 当前默认 runtime root 仍是 `backend/data/`；如果未来迁到 `.atm/`，应通过 runtime root 配置迁移完成，而不是在业务文档里写死新的根目录语义

---

## 9. 目录名与表名不是一回事

当前必须明确区分两套概念：

- 数据库表名：按业务模型命名
- 文件系统目录名：按运行时产物命名

例如：

- 表里是 `raw_file`
- 目录里是 `raw_files/`

例如：

- 表里是 `knowledge_document`
- 目录里是 `knowledge_markdowns/`

不要把目录名误写成数据库表名，也不要反过来。

---

## 10. 删除与重建边界

可以安全重建：

- `temp/`
- `debug/`
- `knowledge_markdowns/_build/`

需要谨慎处理：

- `raw_files/`
- `raw_markdowns/`
- `assets/<file_id>/`
- `knowledge_markdowns/*.md`
- `knowledge_markdowns/manifest.json`
- `backend/data/users/<user_id>/LEARNER.md`
- 未来若启用 `backend/data/users/<user_id>/profile/*`，这些运行时学习档案同样属于谨慎处理范围

---

## 11. 一句话结论

当前仓库的关键事实是：

- 复杂流程真相在 `workflows/`
- 规范基础能力在 `shared/`
- 新代码优先走 `app.shared.*`
- `app.teaching.*` 继续保留兼容语义
- 数据真相在数据库
- 文件真相在 `raw_files / raw_markdowns / assets / knowledge_markdowns / users/*`
- runtime root 的真相源是 `app.shared.infra.runtime_paths`
- 具体业务路径命名必须服从 `app.utils.path_helpers`

## 12. 规范运行时辅助模块

- `app.shared.infra.runtime_paths` 是 runtime root 的规范来源。
- `app.utils.path_helpers` 是运行时业务路径构造的规范来源。
- `app.utils.docgen_store` 是知识文档构建锁、manifest 与运行时构建状态辅助逻辑的规范来源。
- `app.shared.*` 是新的 canonical import path。
- `app.teaching.*` 保持兼容语义，不再作为新实现的主设计入口。
- 不新增顶层 `app/common` 包；workflow 共享编排能力继续放在 `workflows/common`。
