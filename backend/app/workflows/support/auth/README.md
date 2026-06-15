# Auth Support

最后更新：2026-06-15

职责：处理认证相关业务用例，包括访客身份、邮箱注册登录、验证码、access token。

```text
输入: auth request
输出: user identity + token/session payload
```

## 文件

```text
identity.py   # 访客身份、当前用户解析
sessions.py   # 注册、登录、token、会话响应
smtp.py       # 邮箱验证码发送
```

## 主流程

## 1. 访客身份

输入：guest token 或空身份

动作：解析或创建本地访客用户。

输出：

```text
user_id
is_guest
access_token
```

## 2. 邮箱注册/登录

输入：邮箱、密码、验证码或登录凭据

动作：校验用户和密码，创建或刷新会话 token。

输出：

```text
user
access_token
expires_at
```

## 3. 验证码

输入：邮箱地址、验证码用途

动作：生成验证码并通过 SMTP 发送。

输出：发送结果。

## 边界

`auth` 是 support 用例，不是 LangGraph lane。

API 和依赖层通过 `app.workflows.support.auth` 的稳定导出进入。
