# AITeachMe 工作流架构图

> 由 `scripts/generate_workflow_diagrams.py` 从已编译的 LangGraph 拓扑自动生成。
> 运行 `conda run -n atm python scripts/generate_workflow_diagrams.py` 可重新生成。

| 模块 | 文件 | 包含的子工作流 |
|------|------|----------------|
| 🧬 Digest Engine · 消化引擎 | [digest.md](digest.md) | Digest Curriculum Workflow / Digest DocGen Workflow / Digest Graph Workflow / Digest Unified Workflow |
| 📝 Examine Engine · 诊断引擎 | [examine.md](examine.md) | Examine Exam Grade Workflow / Examine Workflow / Examine Question Build Workflow |
| 📥 Ingest Engine · 摄入引擎 | [ingest.md](ingest.md) | Ingest Deep Enhance Workflow / Ingest File Parse Workflow |
| 💬 Interact Engine · 伴读引擎 | [interact.md](interact.md) | Interact Workflow |
| 📊 Profile Engine · 显影引擎 | [profile.md](profile.md) | Profile Workflow |
