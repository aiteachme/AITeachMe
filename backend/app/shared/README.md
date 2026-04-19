# Shared 层说明

最后更新：2026-04-16

`app.shared` 是后端的共享基础层。
它负责收拢那些“离开具体业务依然成立，而且多个模块都会复用”的能力，让上层代码有稳定入口。

对新同学来说，先记住这句话就够了：

> `shared` 解决“共用能力放哪里”，不解决“具体业务怎么跑”。

## 1. 先看整体位置

当前推荐依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

这条链表示：

- `api` 只接 HTTP 请求。
- `workflows` 是唯一业务层。
- `shared.infra` 和 `shared.kernel` 提供可复用底座，不反向依赖业务层。

## 2. `shared` 里有哪些层

`app.shared` 目前分成两层：

| 目录 | 作用 | 当前典型内容 |
| --- | --- | --- |
| `app.shared.kernel` | 最底层原语层 | 异常、时间、ID、领域事件 |
| `app.shared.infra` | 共享基础设施层 | 设置、数据库、存储、LLM、检索、工具、记忆、trace / track、workflow 共用支撑 |

可以把它理解成：

```text
kernel = 不依赖外部系统的基础原语
infra  = 已经接上外部系统的共享能力
```

## 3. `kernel` 现在实际放什么

`app.shared.kernel` 当前很小，但边界很清楚：

- `events.py`
  领域事件原语。
- `exceptions.py`
  统一基础异常。
- `ids.py`
  常用 ID 校验辅助。
- `time.py`
  统一时间辅助。

判断标准：

- 如果这段代码不关心数据库、不关心 LLM、不关心存储、不关心某个 workflow，只是在表达一个稳定原语，它更应该放在 `kernel`。

## 4. `infra` 现在实际放什么

`app.shared.infra` 是共享基础设施层，负责：

- 读取 `.env` 和 `settings_default.yaml`
- 初始化数据库与运行时路径
- 封装本地存储 / S3 存储
- 提供 LLM、trace / track、Prompt、Embedding 等 AI 基础能力
- 提供 Search、Reader、Retriever、Context Compression
- 提供 Tool Registry 与 Toolpack
- 提供共享 Memory、事件日志、通用执行契约

更细的目录导航见：

- [infra/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/README.md)

## 5. 哪些内容不要放进 `shared`

下面这些内容不要放进 `shared`：

- 某个 workflow 专属的 graph、state、node、router
- 某个 workflow 专属的 runtime
- 引擎专属教学表达，例如 Digest 章节脚手架、教学块、教学上下文组织
- 某条业务链专属的 prompt 文本
- “先做什么、后做什么、失败后怎么补救”的业务编排逻辑

对应落点应该是：

- 引擎专属教学语义放对应 `app.workflows.<module>.common`
- 业务编排放 `app.workflows`

## 6. 新同学最常见的判断题

### 情况 1：我想加一个底层能力

例子：

- 新增一个统一的存储 helper
- 新增一个 retriever
- 新增一个工具注册入口

通常放 `app.shared.infra`。

### 情况 2：我想加一个教学能力

例子：

- 新增一个“分步讲题”工具
- 新增章节导学块
- 新增教学上下文拼装规则

通常放对应业务模块：

- Digest 文档教学语义放 `app.workflows.digest.common.pedagogy`
- 通用可执行教学工具放 `app.shared.infra.tools.builtin.teaching_tools`

### 情况 3：我想改某条业务流程

例子：

- Digest 新增一个 graph 节点
- Interact 新增一个对话策略分支
- Examine 新增一个评分阶段

通常放 `app.workflows`。

## 7. 导入规则

建议：

- 基础原语从 `app.shared.kernel.*` 导入
- 基础设施从 `app.shared.infra.*` 导入

不建议：

- 重新创建 `app.services` 或从旧 service 路径导入
- `workflows` 自己再复制一套 LLM、trace / track、Tool Registry

## 8. 新成员阅读顺序

第一次接手后端，建议按这个顺序读：

1. 本文件，先建立 `kernel / infra` 的边界。
2. [infra/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/README.md)，看共享基础设施怎么分层。
3. [workflows/STRUCTURE.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/STRUCTURE.md)，看业务层如何分区。
4. [workflows/README.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/workflows/README.md)，看真正的业务流程怎么编排。

## 9. 一句话总结

- `kernel` 放原语。
- `infra` 放共享基础设施。
- `workflows` 放业务用例、引擎编排，以及“怎么教”的业务语义。
