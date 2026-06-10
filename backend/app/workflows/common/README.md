# Common workflow helpers

最后更新：2026-05-13

`backend/app/workflows/common/` 只放跨 workflow 复用、且仍属于业务 workflow 层的轻量公共能力。

这里不是新的业务引擎，也不是 `shared.infra` 的替代品。它的存在目的是承接少量“所有 workflow 都会用，但又不应该下沉到 infra”的辅助逻辑。

## 当前内容

| 文件 | 作用 |
| --- | --- |
| `model_policy.py` | 合并并压缩 workflow model-policy metadata；提供 `ProviderNativeToolPolicy`，让各 lane 在自己的 model policy 中声明是否允许模型原生 `web_search/file_search` |

## 可以放什么

- 跨多个 workflow 真实复用的纯辅助逻辑。
- 不访问数据库、不发起 LLM 调用、不读写存储的轻量函数。
- 面向 workflow author 的公共契约辅助，例如 model policy metadata、provider-native tool policy、未来的语言策略解析。

如果后续实现英文模式，跨 workflow 的语言解析、`target_language` 标准化、prompt 语言片段构建可以放在这里，例如：

```text
backend/app/workflows/common/language_policy.py
```

但各业务 prompt 仍应留在对应 lane 的 `prompts/` 目录里。

## 不可以放什么

- workflow graph / node / state。
- 某个业务引擎专属的 prompt。
- API 路由参数处理。
- 数据库读写、ContentStore 操作、LLM 调用、检索调用。
- 为了“可能复用”提前上提的单 lane helper。

判断方法：

- 离开具体业务 lane 后仍然成立，才可能进入这里。
- 如果在描述“能力怎么接”，应该去 `app.shared.infra`。
- 如果在描述“教学怎么组织、怎么生成、怎么反馈”，应该留在对应 workflow lane。
