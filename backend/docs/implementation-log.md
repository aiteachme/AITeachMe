# 实现记录

## 已完成

- `app/repositories/models.py` 已拆分到 `app/models/`
- 依赖方向收紧为：
  - `api -> services -> repositories -> models`
  - `services -> agents -> core`
- `agents` 不再直接导入 `Session`、repo 或做数据库写入
- JSON 接口统一为 `ApiResponse`
- `chat/send` 保持原生 SSE
- 列表接口统一切到 `page/size`
- 新增：
  - `files/retry`
  - `files/delete`
  - `knowledge/retry`
  - `knowledge/delete`
  - `chat/clear`
  - `exam/delete`
- parse/build 状态统一为：
  - `pending`
  - `processing`
  - `completed`
  - `failed`
- 新增 `error_message`、`current_step`
- 各 agent 增加了 `prompts/` 目录
- 新增 `app/core/prompt_loader.py`，使用 Jinja2 + StrictUndefined
- 新增根目录 `playground/`

## 当前实现约定

- 顶层知识集合统一叫 `DocSet`
- `DocSet` 下的单篇内容统一叫 `Document`
- 文件侧统一叫 `RawFile`
- 文件删除默认禁止删除已被知识集合引用的源文件
- 知识构建重试只允许最近一次任务处于 `failed`

## 仍可继续增强

- 更细粒度的异步任务管理
- 更完整的数据库迁移策略
- 更多 playground 示例
- 更丰富的向量检索与排序策略
