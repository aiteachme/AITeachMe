# Auth Support

最后更新：2026-08-15

职责：提供游客身份、邮箱密码、可撤销 Cookie 会话、OAuth 身份绑定、限流和显式游客数据迁移。

## 安全边界

- `atm_session` 是随机不透明令牌；数据库仅保存 SHA-256 哈希，可单会话或全账号撤销。
- 登录写请求使用 HttpOnly Cookie，并同时校验 `X-CSRF-Token` 与允许的 Origin。
- access token 必须带 `typ=access`，且只接受 `is_registered=true`、未被合并的用户。旧 Bearer 只保留一版换发 Cookie 的迁移能力。
- guest token 必须带 `typ=guest`，只能恢复未注册且未被合并的游客。`device_key` 不能登录注册账号。
- Android 原生客户端持久化 HttpOnly Cookie，并在登录写请求中携带 CSRF token 与 `aiteachme://android` Origin；该原生 Origin 由后端固定信任，不参与网页 CORS 放行。
- 新密码使用 Argon2id；旧 PBKDF2 哈希在密码登录成功后透明升级。
- OAuth provider token 只用于读取身份，读取后立即丢弃，绝不入库。
- 密码校验分别按邮箱和来源 IP 使用数据库限流桶；OAuth 二次确认复用同一限流边界。

## 文件

```text
identity.py       # 兼容导出：游客身份与 token
sessions.py       # 邮箱注册登录、密码哈希、旧 token
session_store.py  # Cookie 会话、撤销、CSRF/Origin
housekeeping.py   # 过期会话、OAuth flow 与限流桶的分批清理
providers.py      # Google、QQ、微信 OAuth 与身份绑定
rate_limit.py     # 数据库级认证限流
merge.py          # 游客资产摘要、确认与 .atmx 事务化 staging 迁移
smtp.py           # 邮箱验证码
```

## OAuth

- Google：OIDC Authorization Code + PKCE，校验签名、issuer、audience、nonce、有效期和 `email_verified`。
- QQ：QQ 互联网站应用，使用 `openid`，昵称和头像不参与合并判断。
- 微信：开放平台网站扫码，scope `snsapi_login`，优先 `unionid`，否则使用应用作用域 `openid`。
- 同一已验证邮箱不会静默绑定；用户必须再提供原邮箱密码完成所有权确认。
- 用户拒绝授权时仍会立即消费一次性 state，再安全返回站内页面；登录成功后继续提示迁移 OAuth 发起前的游客资产。
- 解绑前必须保证账号仍有密码或另一种第三方登录方式。

## 游客迁移

邮箱密码或 OAuth 登录只创建 `merge_offer`，用户确认后才运行 `user_merge_job`。课程通过现有 `.atmx` 以 `commit=false` 导入目标账号，并在同一数据库事务内保持 `staging`；课程、独立资料、全局聊天、考试和画像全部完成后才统一切换为可见。失败会回滚目标行并清理本次写入的对象存储前缀，源游客数据保持不变。成功后源游客标记 `merged_into_user_id`，保留七天恢复信息；到期清理循环会幂等删除源课程、独立资料、全局聊天、正式 memory、对象存储前缀和本地学习者档案，失败任务在十五分钟后重试。

`auth` 是 support 用例，不是 LangGraph lane。API 和依赖层通过 `app.workflows.support.auth` 的稳定导出进入。

## 后台清理

- 会话访问时间最多每 5 分钟写回一次，避免普通读取和前端轮询持续制造数据库写入。
- 后台任务每小时分批删除已过期的限流桶、OAuth flow 和登录会话；另清理消费时间超过 1 天的 flow，未过期的已撤销会话保留 7 天用于审计。
