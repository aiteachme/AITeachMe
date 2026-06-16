# PostHog 后续埋点规划

## 判断

PostHog 的接入确实简单：前端初始化一次、自动采集页面和点击、后台直接出图。真正需要设计的是“事件口径”，否则后面数据会乱。当前已完成 `analytics.ts` 初始化、脱敏、`$pageview`、`$autocapture`、身份同步；`AnalyticsProvider` 挂根，`RouteAnalyticsBridge` 记录路由，`TopBar` 记录登录/注册/退出。Activity 已能看到事件，说明基础链路成立。

## 总目标

不把每个按钮都手写埋点。普通浏览和点击交给 `$pageview`、`$autocapture`；关键业务动作补稳定事件名。最终后台要能看：用户从哪来、访问哪些页面、点击哪些入口、核心流程哪里流失、AI/文档/考试任务成功率和耗时。

## 看板规划

1. 总览看板：DAU、WAU、访问次数、登录用户占比、匿名用户占比、新老用户、设备和浏览器。

2. 页面看板：用 `$pageview` + `route_path` 统计首页、学习空间、资料库、课程页、考试页、设置页、个人页访问量和停留趋势。

3. 功能看板：用命名事件看上传资料、新建课程、打开 AI 窗口、发送对话、生成文档、开始考试、提交考试。

4. 质量看板：展示任务成功率、失败率、平均耗时、失败原因分类。该部分以后由后端补充。

## 事件分层

1. 自动事件：保留 `$pageview`、`$autocapture`，用于发现用户真实点击路径。

2. 前端命名事件：只补关键动作，如 `library_upload_started/succeeded/failed`、`course_created/opened/imported`、`chat_message_sent/response_received/response_failed`、`digest_started/completed/failed`、`exam_started/submitted/graded`、`profile_viewed/updated`。

3. 后端任务事件：记录工作流类型、模型、耗时、状态、失败分类；不记录正文、prompt、答案、文件名。

## 漏斗优先级

第一批做三个漏斗：访问首页到创建课程；上传资料到资料入库成功；打开 AI 窗口到收到回复。第二批做文档生成和考试提交。这样最能覆盖当前平台主路径。

## 隐私和环境

线上默认 `VITE_POSTHOG_DEBUG=false`、`VITE_POSTHOG_SESSION_REPLAY=false`。Replay 如需开启，只给内测或低采样。继续保持文本遮罩、属性过滤、路由参数归一化，避免上传用户内容。

Sealos/Nginx 前端镜像通过启动脚本生成 `/runtime-config.js`，前端 analytics 初始化优先读取其中的 `VITE_POSTHOG_*`。因此线上修改前端 PostHog 配置时，改 Sealos 前端 App 的运行时环境变量并重启/滚动容器即可。脚本兼容读取同一前端容器里的 `POSTHOG_*` 作为兜底；后端事件仍由后端 App 的 `POSTHOG_*` 控制。

## 验收

每新增事件先在 Activity 看到，再进入 Dashboard。一个事件必须有明确用途、稳定命名、无敏感字段。优先做看板和核心点击，再补业务闭环，最后接后端耗时和失败率。
