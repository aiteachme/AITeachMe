# AITeachMe 工作流架构图

> 由 `backend/scripts/generate_workflow_diagrams.py` 从已编译的 LangGraph 拓扑自动生成。
> 运行 `conda activate atm && python backend/scripts/generate_workflow_diagrams.py` 可重新生成。

## 图例说明

| 元素 | 含义 |
|------|------|
| `▶ START` (绿色) | 工作流入口 |
| `⏹ END` (红色) | 工作流出口 |
| `⚠ Fail xxx` (深红) | 错误处理节点 |
| 药丸形节点 (蓝色) | 终结/收尾节点 |
| 方形节点 (深灰) | 普通处理节点 |
| `✓` 实线箭头 | 正常流转（Happy Path） |
| `✗ err/fail` 红色虚线 | 错误/中断路径 |
| `Send xN` 虚线 | Fan-out 并行分发 |

## 模块索引

| 模块 | 文件 | 包含的子工作流 |
|------|------|----------------|
| 🧬 Digest Engine · 消化引擎 | [digest.md](digest.md) | Digest Planner Workflow / Digest DocGen Workflow / Digest Graph Workflow |
| 📝 Examine Engine · 诊断引擎 | [examine.md](examine.md) | Examine Question Build Workflow / Examine Exam Grade Workflow / Examine Workflow |
| 📥 Ingest Engine · 摄入引擎 | [ingest.md](ingest.md) | Ingest File Parse Workflow / Ingest Deep Enhance Workflow |
| 💬 Interact Engine · 伴读引擎 | [interact.md](interact.md) | Interact Workflow |
| 📊 Profile Engine · 显影引擎 | [profile.md](profile.md) | Profile Pipeline Workflow / Profile Workflow |
