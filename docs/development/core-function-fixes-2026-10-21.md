# 核心功能修复与发布验收（2026-10-21）

## 修复内容

本次沿用已合并 `dev_cy` 的 `3d86b48c`，修复实际复现的基础设施问题，没有调整五大引擎边界或手动修改 Orval 生成客户端。

- Responses 流收到 `response.completed` 后立即结束并释放连接，不再等待 HTTP EOF。明确处理 `response.failed`、`response.incomplete` 和 `error`，保留上游错误原因；已输出正文后不自动重试，避免重复正文或把失败流当成成功。
- 补齐端点故障分类：Responses 事件中的 `server_error` / `overloaded` 在正文输出前可按已有配置切换备用端点；并发限流、请求无效和输出截断不因此切换。
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
| 全量后端测试 | 首轮 1937 passed、3 skipped；过载换源补修后 1944 passed、3 skipped |
| 全量前端现有测试 | 167 passed |
| 前端生产构建 | 通过；保留既有大 chunk 提示 |
| 文档站生产构建 | 按锁文件安装依赖后构建通过 |
| Alembic 升级 SQL 安全检查 | 通过 |
| OpenAPI 同步检查 | 通过 |
| 最终相关模块回归 | 81 passed |
| 上传 Markdown、解析、独立身份访问隔离 | 通过；跨身份预期 404 |
| 伴读 SSE、聊天历史 | 通过，首个正文约 3.51 秒，无错误事件 |
| 默认规划 → 讲义 → 图谱 | 通过，三个运行状态均 completed，约 340.31 秒 |
| 新课程出题 → 提交 → 批改 → 画像 | 通过，graded、profile_sync.completed，更新 2 个知识状态和复习任务 |
| 导入课程出题 → 批改 → 画像 → 复习指南 | 通过，复习指南摘要非空，含 2 项行动建议与 2 个重点知识点；完成后再删除临时课程 |
| 显式 reason 规划路径 | 通过，诊断、草案与确认约 30.05 秒 |
| PDF、DOCX、PPTX 小型中文样本 | 全部 ready_for_digest，约 15.81 秒 |
| 带图 PDF → 图片理解 → 讲义与图谱 | 通过，MinerU 识别 1 张图片，运行状态确认 image_understanding_enabled=true，约 123.06 秒，讲义 1655 字符 |
| 演示课远程冷缓存导入 | 两轮成功；导入后新生成试卷、批改与画像同步成功 |
| 微信、飞书社区二维码 | 均 200，并验证图片内容有效 |
| 浏览器讲义、图谱、训练中心 | 通过；1037×881 窗口中正常点击收起图谱，临时课程通过界面删除 |

默认建课实测中，上游发生过过载错误并恢复，端到端构建因此比修复前某次成功复现更慢。上述结果证明小样本流程可完成，不代表任意上游网络状况、大资料或多人并发都有相同时延。

推送前发现本地 `node_modules` 使用旧版 Orval 8.10.0，而锁文件要求 8.18.0。执行 `npm ci` 同步依赖后，重新生成客户端与已提交内容完全一致，推送钩子的 OpenAPI/Orval 和 Android API 合同检查均通过。同步依赖后的前端 167 项现有测试与生产构建再次通过，没有手工修改生成文件。

脱敏原始证据保存在 Git 忽略的 `.tmp-core-recheck/`：`local_fixed_default.json`、`local_fixed_reason.json`、`local_fixed_formats.json`、`local_fixed_demo.json`、`local_final_cold_demo.json`、`local_final_assets_corrected.json`、`local_final_study_guide.json`、`local_final_multimodal.json`、`local_final_browser.json`。脚本创建的课程和资料均已清理，证据不保存密钥或会话令牌。

## 发布与线上验收

修复提交已推送到 `origin/hotfix/core-function-reliability`，代码提交为 `1a25d9c7`，其前包含 reader 安全修复 `47467a92` 和 `dev_cy` 合并 `3d86b48c`。

用户已明确授权本次将已验收修复快进推送 main，随后等待 CI 与自动部署并复验线上，作为仓库通常 PR 流程的单次例外。发布前重新 fetch 确认远程 main 仍为 `84c40281` 且是修复分支祖先，采用非强制快进推送。临时修复分支会在成功合入并验收后清理，保留其他开发分支、工作区和已有 stash。

首次发布 `1611c13a` 的 [CI 39587926508](https://github.com/aiteachme/AITeachMe/actions/runs/39587926508) 和 [Deploy 39588154892](https://github.com/aiteachme/AITeachMe/actions/runs/39588154892) 均成功，前后端已完成 Sealos 部署，数据库启动、健康与上传检查通过。Cloudflare Pages 未启用，其上传步骤正常跳过。

首次发布后的真实复验中，上传、伴读、PDF/DOCX/PPTX 和二维码通过，但规划返回 502。LangSmith `atm-cloud` 确认 `course_5bjz0ha7ny59` 两次主通道诊断调用均返回 `response.failed/server_error` 过载：LLM span 为 `01a15e23-0505-78f2-ac49-9aa7ea78d197` 与 `01a15e23-178f-7233-9149-b0d82e4ef234`。这不是仅仅加载较慢；后续无知识点不能出题的 409 是建课失败的结果。

同时复现端点分类遗漏：这种原生事件转成的异常未被识别为可换源故障，配置好的备用通道会被跳过。已补齐分类。新回归在修复前为 1 failed、1 passed，修复后验证未输出正文时切换备用成功，已有正文时不换源也不重复输出；并覆盖截断、无效请求及并发限流的边界。补修后全量后端 1944 项通过，本地正常服务的完整学习流程通过：建课约 130.73 秒，出题、批改、画像与复习指南约 24.21 秒，临时数据清理成功。

首次发布前端的实际浏览器验收也通过：图片理解开关可见，演示课程从界面导入，1037×881 窗口中讲义、图谱正常，正常点击收起成功，训练中心可进入且无控制台错误。补修只修改后端故障分类，随后仍需跟踪该补修的 CI、部署及线上复验。

### 当前线上旧版的补充复验

2026-10-21 18:20–18:24（北京时间）重新检查线上当时运行的 `84c40281`。GitHub 查询确认该 SHA 的既有 CI、Deploy 均成功，修复分支还没有 PR，也未触发新版本发布。

| 当前线上验证项 | 本轮结果 |
| --- | --- |
| 首页 | 正常显示；浏览器控制台无错误 |
| Markdown 上传解析与跨身份隔离 | 通过；跨身份返回预期 404 |
| 伴读 SSE 与历史持久化 | 通过；首个正文约 3.29 秒，有 done，无 error |
| 规划 → 讲义 → 图谱 | 通过；约 157.75 秒，三个状态均 completed，发布讲义 1730 字符 |
| 新生成试卷 → 提交 → 批改 → 画像 | 通过；约 25.41 秒，profile_sync.completed，更新 2 个知识状态和复习任务 |
| 批改后复习指南 | 通过；摘要非空，含 2 项行动建议及 2 个重点知识点 |
| PDF、DOCX、PPTX | 全部 ready_for_digest，约 38.37 秒 |
| 演示目录与社区二维码 | 均 200；二维码图片内容校验通过 |

本轮建课等待后成功完成，未出现 HTTP/SSE 错误。它与此前真实返回 502 的故障复现属于不同请求，不用于否定历史故障或证明待发布修复已生效。两个隔离测试身份创建的课程与资料都已删除，脱敏证据见 `.tmp-core-recheck/online_before_release_full_20261021.json`、`online_before_release_formats_20261021.json` 及 `online_before_release_assets.json`。
