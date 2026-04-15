# Teaching Tools 模块说明

最后更新：2026-04-16

`teaching_tools/` 是教学工具实现的 canonical 模块。

它不是独立教学层，也不是某条 LangGraph lane。它只承接“跨引擎复用、需要通过 agent tool registry 暴露”的业务教学原子函数。

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

## 分类规则

- 注册机制归 `app.shared.infra.tools.teaching_registry`
- 跨引擎复用的教学工具实现归 `workflows/support/teaching_tools`
- 单条链路私有的教学逻辑归对应 lane 的 `nodes/` 或 `lib/`
- Digest 文档生成专属教学表达归 `workflows/digest/_shared/pedagogy`
- 不再恢复 `backend/app/teaching` 作为兼容层或正式层
