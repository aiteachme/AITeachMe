# Skills

`backend/skills/` 存放项目内置的 `SKILL.md` 策略包。

Skill 不是可执行工具，也不是插件代码。它的作用是把一段经过整理的教学/检索/写作策略按需渲染进 LLM prompt。

## 运行方式

一次 Digest 构建可以在请求或已确认方案里携带：

```json
{
  "selected_skillpacks": ["find_resources", "explain_with_analogy"]
}
```

运行时会根据 `prompt_scope` 过滤：

- `digest.planner`
- `digest.docgen.research`
- `digest.docgen.writer`
- 未来可扩展到 `interact` / `examine`

匹配后，系统会：

1. 读取对应 `SKILL.md`
2. 绑定参数与 defaults
3. 渲染 Markdown 正文为 prompt 片段
4. 收集 `recommended_tool_tags`
5. 把这些内容交给当前 workflow 的 prompt builder

Skill 不会直接执行 `web_search`、`search_kb` 或任何 Python 代码。

## 当前定位

- 当前主要服务 Digest planner / docgen。
- 后续如果前端提供入口，只建议让用户选择系统内置 preset。
- 不开放普通用户自由上传任意 skill；自定义 skill 更适合作为本地开发或部署方能力。

## 与 Toolpack 的区别

- skill：告诉模型“怎么做”，通过 prompt 起作用。
- toolpack：提供真实 Python handler，注册可执行动作。
