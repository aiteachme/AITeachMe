# Teaching Tools 模块说明

最后更新：2026-04-16

`teaching_tools/` 是教学工具实现的 canonical 模块。

## 分工

- `app.shared.infra.tools.teaching_registry`
  负责教学工具的注册、枚举、执行与 registry 同步
- `workflows/support/teaching_tools/commands.py`
  负责教学工具本体实现
- `workflows/support/teaching_tools/queries.py`
  负责查询型门面

## 为什么放在 support

- 这些函数属于业务层，不是纯基础设施
- 它们也不是 LangGraph 链路，不应该塞进五大引擎目录
- 它们更像“可被 AI 或 API 直接调用的业务能力”
