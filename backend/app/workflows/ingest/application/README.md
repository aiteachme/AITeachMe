# Ingest Application

`application/` 是 `ingest` 模块的 API-facing / module-facing 用例落点。

当前 canonical 入口：

- `parse_files.py`
  - `run_parse_file_workflow`
  - `create_parse_file_initial_state`
  - `_run_deep_enhance_background`
- `recovery.py`
  - `recover_stalled_enhancements`
- `exports.py`
  - `WORKFLOW_EXPORTS`

说明：

- `fast_parse/` 与 `deep_enhance/` 仍然是 ingest 的真实链路。
- 模块根的 `runtime.py`、`recovery.py`、`exports.py` 现在只保留兼容导入面。
