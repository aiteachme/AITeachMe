# Common Workflow Helpers

最后更新：2026-06-15

`common/` 只放跨多个 workflow 真实复用、且仍属于业务 workflow 层的轻量辅助。

```text
workflow lane
  -> workflows/common helper
  -> lane-local model_policy / prompt / graph
```

## 当前内容

| 文件 | 作用 |
| --- | --- |
| `model_policy.py` | 合并和压缩 workflow model-policy metadata；声明 provider-native tool policy |

## 可以放

```text
跨多个 workflow 复用
不访问数据库
不调用 LLM
不读写存储
不属于 infra 的业务辅助
```

例子：

```text
model policy metadata helper
provider-native tool policy
未来的 target_language / language_policy 解析
```

## 不可以放

```text
graph / node / state
单个业务引擎专属 prompt
API 路由参数处理
数据库读写
ContentStore 操作
LLM 调用
检索调用
为了可能复用提前上提的 helper
```

## 判断规则

离开具体业务 lane 后仍然成立，才可能进入 `workflows/common`。

如果是在描述“能力怎么接”，应进入 `app.shared.infra`。

如果是在描述“教学怎么组织、怎么生成、怎么反馈”，应留在对应 workflow lane。
