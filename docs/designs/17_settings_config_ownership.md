# 设置与配置归属

本文档定义 AITeachMe 当前配置系统的归属边界、存储位置，以及本地模式 / 云端模式下设置页面的开放范围。

## 1. 当前统一口径

配置分成四层：

1. `env`：部署级、敏感、基础设施连接
2. `code defaults`：代码里的项目默认行为
3. `system_runtime_settings`：数据库中的全局非敏感运行覆盖
4. `browser local`：当前浏览器本机项

另外存在一个**可选**来源：

- `PROJECT_SETTINGS_PATH` 指向的外部项目 settings override 文件

它不是 repo 必备文件，只有显式配置时才参与 merge。

## 2. 各层职责

### 2.1 env

负责：

- `LLM_API_KEY`
- `DATABASE_URL`
- `SMTP_*`
- `S3_*`
- `AUTH_*`
- `LANGSMITH_*`
- `APP_MODE`

这些属于部署输入，不属于普通业务参数。

### 2.2 code defaults

负责系统能跑起来的默认行为，例如：

- 模型路由默认值
- planner / ingest / docgen / search / rag 默认参数
- observability 默认参数

当前代码默认值集中放在：

- `backend/app/shared/infra/settings/defaults.py`

这也是现在唯一的默认值真源。

### 2.3 external project override

如果配置了 `PROJECT_SETTINGS_PATH`，则会在 code defaults 之上额外叠加一份项目级 override 文件。

这个文件适合放：

- 少量需要版本化 review 的项目策略
- 某个部署环境的固定项目覆盖

但它不是 repo 必需文件，也不是日常本地开发必需文件。

### 2.4 system_runtime_settings

负责本地模式下的系统级非敏感覆盖。

当前它是数据库里的全局真相层，用来覆盖：

- code defaults
- optional external project override

适合保存：

- 模型路由
- ingest / planner / docgen / interact / search / rag 参数
- observability 非敏感参数

### 2.5 browser local

只保存当前浏览器有效的本机项：

- `apiUrl`
- `useMock`
- `debugMode`
- 本地模式下的临时 `MinerU Token`

这些值不会成为服务端配置真相。

## 3. 本地模式

本地模式默认把当前操作者视为单机管理员。

规则：

- 所有配置输入项可读可写
- 所有派生 / 诊断 / 健康状态项只读

### 本地模式可写项

- `.env` 中暴露的部署级配置
- `system_runtime_settings`
- 浏览器本机项

### 本地模式设置页

本地模式设置页仍然是完整管理员控制台，但默认不再等价于“把全部可写配置一次性摊开”。

当前策略：

- 默认先展示常用设置
- 低频调优项通过“显示高级”进入
- 高风险部署项继续留在 `.env`
- 更底层的项目级调优优先收回代码默认值
- 只有显式配置 `PROJECT_SETTINGS_PATH` 时才会叠加外部项目 override

## 4. 云端模式

云端模式下，普通用户不再拥有服务端设置权限。

规则：

- env：只读
- `system_runtime_settings`：只读
- browser local：普通用户默认不暴露

云端普通用户看到的是只读状态页：

- 运行模式
- 当前模型 / 向量 / 搜索 / 存储 / 鉴权状态
- 关键 env 是否已配置
- 配置来源说明

不会出现任何服务端可写控件。

## 5. Parser 配置语义

当前 `ingest.default_parser_provider` 只允许：

- `auto`
- `markitdown`
- `mineru`

其中：

- `auto` = 后端本地自动 parser chain
- `markitdown` = 显式优先 MarkItDown
- `mineru` = 显式优先 MinerU

`docling` / `unstructured` 当前未接入真实执行链，因此不再作为可选项暴露。

## 6. 已知高级配置

以下配置当前保留在 code defaults / optional project override，不进入普通设置页：

- `models.overrides`
- `search.retriever_profiles`

原因：

- `models.overrides` 还未接入模型解析主链路
- `search.retriever_profiles` 更适合作为版本化项目配置，而不是日常 UI 表单

## 7. 一句话

现在的配置真相顺序是：

`env + code defaults + optional project override + system_runtime_settings + browser local`
