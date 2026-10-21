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

修复最初推送到 `origin/hotfix/core-function-reliability`，主要代码提交为 `1a25d9c7`，其前包含 reader 安全修复 `47467a92` 和 `dev_cy` 合并 `3d86b48c`。最终过载换源补修为 `ab42a08e`，已推送 main 并完成生产部署。

用户已明确授权本次将已验收修复快进推送 main，随后等待 CI 与自动部署并复验线上，作为仓库通常 PR 流程的单次例外。首次发布前重新 fetch 确认远程 main 仍为 `84c40281` 且是修复分支祖先，采用非强制快进推送。最终验收后已删除本次本地和远程 `hotfix/core-function-reliability`，保留其他开发分支、工作区和已有 stash；重新 fetch 确认远程 `dev_cy` 已全部包含于 main。

首次发布 `1611c13a` 的 [CI 39587926508](https://github.com/aiteachme/AITeachMe/actions/runs/39587926508) 和 [Deploy 39588154892](https://github.com/aiteachme/AITeachMe/actions/runs/39588154892) 均成功，前后端已完成 Sealos 部署，数据库启动、健康与上传检查通过。Cloudflare Pages 未启用，其上传步骤正常跳过。

首次发布后的真实复验中，上传、伴读、PDF/DOCX/PPTX 和二维码通过，但规划返回 502。LangSmith `atm-cloud` 确认 `course_5bjz0ha7ny59` 两次主通道诊断调用均返回 `response.failed/server_error` 过载：LLM span 为 `01a15e23-0505-78f2-ac49-9aa7ea78d197` 与 `01a15e23-178f-7233-9149-b0d82e4ef234`。这不是仅仅加载较慢；后续无知识点不能出题的 409 是建课失败的结果。

同时复现端点分类遗漏：这种原生事件转成的异常未被识别为可换源故障，配置好的备用通道会被跳过。已补齐分类。新回归在修复前为 1 failed、1 passed，修复后验证未输出正文时切换备用成功，已有正文时不换源也不重复输出；并覆盖截断、无效请求及并发限流的边界。补修后全量后端 1944 项通过，本地正常服务的完整学习流程通过：建课约 130.73 秒，出题、批改、画像与复习指南约 24.21 秒，临时数据清理成功。

首次发布前端的实际浏览器验收也通过：图片理解开关可见，演示课程从界面导入，1037×881 窗口中讲义、图谱正常，正常点击收起成功，训练中心可进入且无控制台错误。该浏览器临时课程已通过界面确认删除，侧栏恢复“暂无课程”。

### 最终补修发布与线上复验

实际部署并验收的应用代码 SHA 为 `ab42a08ec09e435a20096161a7d8e33636b673ee`。[CI 39590662713](https://github.com/aiteachme/AITeachMe/actions/runs/39590662713) 的前端构建、文档构建和后端检查全部成功；[Deploy 39590950563](https://github.com/aiteachme/AITeachMe/actions/runs/39590950563) 于北京时间 19:28:15 全部成功，Sealos 前后端均完成发布，后端启动证据、健康、上传及运行策略检查通过。Cloudflare Pages 未启用，其上传步骤跳过。

后端发布完成后，于北京时间 19:26–19:36 使用独立测试身份实测新版本；前端发布完成后重新加载线上页面检查。

| 最终线上验证项 | 结果 |
| --- | --- |
| Markdown 上传解析与跨身份隔离 | 通过；跨身份预期 404 |
| 伴读 SSE 与历史保存 | 通过；首个正文约 3.39 秒，有 done、无 error |
| 默认规划 → 讲义 → 图谱 | 通过；约 170.31 秒，三个状态均 completed，讲义 1993 字符 |
| 新生成试卷 → 提交 → 批改 → 画像 → 复习指南 | 通过；约 25.24 秒，graded、profile_sync.completed，更新 2 个知识状态和复习任务 |
| 演示课程远程导入 | 通过；约 4.75 秒，导入 181 个知识点和 391 条知识关系，未使用本地课包上传替代 |
| 导入课程新生成试卷 → 批改 → 画像 → 复习指南 | 通过；约 24.04 秒，画像同步完成，复习指南非空 |
| PDF、DOCX、PPTX 中文样本 | 全部 ready_for_digest；约 14.89 秒 |
| 带图 PDF → 图片理解 → 讲义与图谱 | 通过；约 203.54 秒，MinerU 识别 1 张图片，运行时开关为 true，讲义 1612 字符 |
| 显式 reason 模型规划 | 通过；约 27.72 秒，方案生成及确认成功 |
| 演示目录、微信和飞书二维码 | 全部 200；二维码图片内容有效 |
| 新版本浏览器首页 | 正常显示，图片理解及演示课程入口可见；控制台 0 errors、0 warnings |
| 主流程期间健康检查 | 14/14 次均 200；客户端测得中位耗时 248.5 毫秒、最大 1163 毫秒 |
| 临时数据清理 | 5 个 API 测试课程全部删除；浏览器测试课程也已删除 |

本轮主流程的 HTTP/SSE 请求没有终止错误。LangSmith `atm-cloud` 仍记录到一次讲义一致性检查的上游 `InternalServerError`：`01a15e38-555d-7cc0-8261-fcb1613400b7`，随后同一节点的 `01a15e38-cfa6-71d0-9044-4c5b78a6eb96` 成功，工作流最终完成。不能将这次自动恢复描述为上游从未出错，也不能将此前真实 502 描述成单纯等待。

多模态测试完成后立即删除临时课程，取消了当时刚启动的章末测验预生成；对应 19:34:58 的 `Question prompt planning was cancelled` 与删除动作一致。该取消与正常出题验收区分记录。演示课程后台向量重建曾保持运行，最终约 444.36 秒完成，status=completed、warning_count=0；导入接口返回时间不等于全部后台向量已就绪。最终查询本轮 5 个课程的追踪没有未结束 span，错误查询和根工作流查询均未达到 100 条上限；默认课程的普通抽样达到上限，不将抽样计数当作全量调用数。

本轮实际模型调用观察到的是主端点，未主动制造线上故障验证备用端点切换。过载事件换源及正文输出后的失败边界由本地核心回归覆盖；线上备用开关未读取确认，不声称本轮实际走过备用端点。这些结果证明本轮小样本主要功能可完成，后台向量重建和模型调用仍受上游时延影响，不作为大资料或多人并发的性能承诺。

脱敏证据位于 Git 忽略目录 `.tmp-core-recheck/`：`online_release_ab42_final_summary.json`、`online_release_ab42_final_traces.json`、`online_release_ab42_review_recovery.json`、`online_release_ab42_cleanup_traces.json`、`online_release_ab42_import_background_final.json` 及对应 `core`、`demo`、`multimodal`、`formats`、`reason`、`assets`、`browser` 文件。本轮本地验收后端进程已停止，未修改用户的 sandbox 设置。

后续仅更新本验收文档的提交使用 `[skip ci]`，避免再次部署相同应用代码；以上 CI/Deploy 链接和线上结果均对应已验收应用代码 `ab42a08e`，不将仅文档的新 HEAD 冒充经过完整部署的 SHA。

### 发布前旧版的历史复验

2026-10-21 18:20–18:24（北京时间）重新检查线上当时运行的 `84c40281`。GitHub 查询确认该 SHA 的既有 CI、Deploy 均成功，修复分支还没有 PR，也未触发新版本发布。

| 发布前旧版验证项 | 当时结果 |
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
