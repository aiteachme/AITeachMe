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

- research micro-loop
- query planner 更细粒度 gap detection
- domain-aware retrieval path

### 批次 B

- systematic / sprint 更严格 chapter contract
- docgen asset sidecar
- 交互 HTML / richer media slot

### 批次 C

- Interact 复用同一套 selected skillpacks
- teaching persona / style 不再另起配置系统

## 验证要求

- skillpack contract 测试
- toolpack loader 测试
- workflow runtime trace 测试
- docgen research / writer 回归测试
- 非 digest 引擎行为不变
