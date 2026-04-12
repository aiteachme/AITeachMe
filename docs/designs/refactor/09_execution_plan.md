# 09. Execution Plan

## 本轮已执行的落地点

### 1. 基础边界

- `shared/infra/traced_execution.py` 成为 canonical traced execution helper
- `shared/infra/execution.py` 退化为兼容 re-export
- `shared/infra/orchestrators/` 已删除
- `shared/infra/prompt_builders/` 已删除

### 2. DocGen runtime 迁移

- `workflows/digest/docgen/runtime/research.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`

节点侧已经改为直接依赖 workflow-local runtime。

### 3. Skillpack 主流程接入

- skillpack metadata 已支持：
  - `prompt_scope`
  - `recommended_tool_tags`
  - `defaults`
- planner API / draft / confirmed plan / docgen state 已支持 `selected_skillpacks`
- planner prompt 与 docgen runtime prompt 已注入 scoped skillpack guidance

### 4. Toolpack 扩展

- external tool loader 已支持 `manifest.yaml + handler.py`
- 扫描路径：
  - `backend/toolpacks`
  - `~/.atm/toolpacks`
- YAML-only `backend/tools/*.yaml` 降级为过渡态

## 当前已知未完成的关键差距

- `retrieval_profile` 已经真正进入 `DocGenResearchRuntime` 的 retriever 工厂，`requested_profile / applied_profile` 也已写入 trace；当前剩余重点变成 micro-loop 调参、学科化 source weight 和缓存。
- `systematic / sprint` 的章节执行合同已进入 confirmed plan -> assignment -> writer/runtime，但后续仍可继续细化到更多学科模板。
- `interactive_html` sidecar 已具备最小执行链，`animation` 仍只保留 contract / trace 预留位，尚未进入首轮主线。
- `inject_examine` 已升级为 digest-local 的模式感知 practice layer，但还没和独立 Examine 引擎共享更深的题目上下文。

## 当前代码检查点

### `shared/infra`

- 保留通用 helper、tool registry、toolpack loader、skillpack loader
- 顶层只保留少量兼容 shim，如 `execution.py`、`llm.py`、`model_router.py`

### `teaching`

- 继续拥有教学脚手架与 teaching-owned tool
- 不新增第二套 runtime

### `workflows`

- graph/state 保持原状
- DocGen business runtime 已归位

## 下一个开发批次

### 批次 A

- research micro-loop 调参
- query planner 更细粒度 gap detection
- domain-aware retrieval weight / cache

### 批次 B

- systematic / sprint 更细学科 contract
- richer asset sidecar
- animation / 更丰富的 media slot

### 批次 C

- Interact 复用同一套 selected skillpacks
- teaching persona / style 不再另起配置系统

## 验证要求

- skillpack contract 测试
- toolpack loader 测试
- workflow runtime trace 测试（trace 结构与字段对照见 `backend/app/workflows/LANGSMITH.md`）
- docgen research / writer 回归测试
- interactive asset / practice layer 回归测试
- 非 digest 引擎行为不变
