# 核心功能修复与发布验收（2026-10-21）

## 修复内容

本次沿用已合并 `dev_cy` 的 `3d86b48c`，修复实际复现的基础设施问题，没有调整五大引擎边界或手动修改 Orval 生成客户端。

- Responses 流收到 `response.completed` 后立即结束并释放连接，不再等待 HTTP EOF。明确处理 `response.failed`、`response.incomplete` 和 `error`，保留上游错误原因；已输出正文后不自动重试，避免重复正文或把失败流当成成功。
- LiteLLM 原生 Responses 迭代器没有 `aclose()` 时，关闭它持有的 HTTPX response；成功、失败、超时和取消都经过同一清理路径。
- 演示课程目录、课程包与社区二维码增加 GitHub 官方 Contents API 备用来源，去掉随机缓存穿透参数。课程包换源从零写入，继续校验大小与 SHA-256；网络连接错误转换为明确的上游下载错误，清理临时文件。
- 保留并完成此前审查中的公共网页 reader 修复：校验全部 DNS 地址、连接已验证公网 IP、保留 Host/TLS SNI、逐跳验证重定向并隔离跨源认证。
- 保留合并时的图文构建合同修复、真实流式兼容修复及窄窗口图谱关闭按钮修复。

## 故障原因与证据

历史本地建课约 74 秒的 `httpx.ReadTimeout` 确实返回 502，不是页面等待后成功。不能把所有历史读取超时都归因于终止事件处理。

本轮结合 LangSmith 和实际 SSE 事件确认：上游有时明确返回 `response.failed`，原因是 `server_error` / “Our servers are currently overloaded”。修复前它被误记为 `empty_llm_response`；修复后日志能保存真实原因，正文输出前按现有策略重试。没有提高超时值掩盖问题，也没有把部分输出当作完整结果。

另实测 C 语言课程包：原 raw GitHub 地址多次读取超时，官方 Contents API 返回完整的 369346 字节，SHA-256 与公开目录一致。冷缓存导入也实际成功，不以本地已有课程包替代远程导入结果。

## 本地验收

使用 conda `atm`、独立临时数据目录和正常 Uvicorn 服务验证，启用 LangSmith，关闭启动时 OpenAPI/Orval 自动重生成。

| 验证项 | 结果 |
| --- | --- |
| 全量后端测试 | 1937 passed、3 skipped |
| 全量前端现有测试 | 167 passed |
| 前端生产构建 | 通过；保留既有大 chunk 提示 |
| Alembic 升级 SQL 安全检查 | 通过 |
| OpenAPI 同步检查 | 通过 |
| 最终相关模块回归 | 81 passed |
| 上传 Markdown、解析、独立身份访问隔离 | 通过；跨身份预期 404 |
| 伴读 SSE、聊天历史 | 通过，首个正文约 3.51 秒，无错误事件 |
| 默认规划 → 讲义 → 图谱 | 通过，三个运行状态均 completed，约 340.31 秒 |
| 新课程出题 → 提交 → 批改 → 画像 | 通过，graded、profile_sync.completed，更新 2 个知识状态和复习任务 |
| 显式 reason 规划路径 | 通过，诊断、草案与确认约 30.05 秒 |
| PDF、DOCX、PPTX 小型中文样本 | 全部 ready_for_digest，约 15.81 秒 |
| 演示课远程冷缓存导入 | 两轮成功；导入后新生成试卷、批改与画像同步成功 |
| 微信、飞书社区二维码 | 均 200，并验证图片内容有效 |

默认建课实测中，上游发生过过载错误并恢复，端到端构建因此比修复前某次成功复现更慢。上述结果证明小样本流程可完成，不代表任意上游网络状况、大资料或多人并发都有相同时延。

脱敏原始证据保存在 Git 忽略的 `.tmp-core-recheck/`：`local_fixed_default.json`、`local_fixed_reason.json`、`local_fixed_formats.json`、`local_fixed_demo.json`、`local_final_cold_demo.json`、`local_final_assets_corrected.json`。脚本创建的课程和资料均已清理，证据不保存密钥或会话令牌。

## 发布与线上验收

本节将在修复推送、CI、部署及线上重新验收完成后记录实际结果；当前不将旧版本的验收结果作为本次发布依据。
