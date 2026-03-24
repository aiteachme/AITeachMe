# Digest 统一构建快速开始

## 1. 入口

统一构建只有一个正式入口：

- HTTP：`POST /api/v1/subjects/{subject}/knowledge/build`
- Python：`app.workflows.digest.unified.runtime.run_unified_digest_build`

示例：

```python
from app.workflows.digest.unified.runtime import run_unified_digest_build

result = await run_unified_digest_build(
    subject="linear_algebra",
    file_ids=[1, 2, 3],
    user_prompt="重点讲解特征值和特征向量",
)

print(result.success)
print(result.doc_count)
print(result.new_node_count)
print(result.curriculum_ready)
```

---

## 2. 对外语义

`/knowledge/build` 的对外语义是：

- 受理一次 unified build
- 后台异步执行
- 不返回 docs/graph 的内部 job 状态
- 前端通过 `/knowledge/docs` 和 `/knowledge/overview` 读取 live 已发布结果

---

## 3. 当前主链

```
knowledge/build
  -> shared prepare
  -> doc/kg 并行
  -> consistency
  -> repair
  -> curriculum
  -> publish outputs
```

注意：

- doc lane 只做 staging
- curriculum 成功之后才 publish live docs

---

## 4. 调试方法

### 4.1 shared prepare

```python
from app.workflows.digest.shared.prepare import prepare_shared_inputs

shared = await prepare_shared_inputs("test_subject", [1, 2, 3])
print(len(shared.source_packets))
print(len(shared.section_packets))
print(len(shared.asset_registry.assets))
```

### 4.2 观察日志

重点看：

- `shared_prepare_started`
- `unified_parallel_lanes_started`
- `kg_extract_started`
- `unified_curriculum_started`
- `unified_publish_completed`

如果没有 `unified_publish_completed`，说明 live docs 还没有切换。

---

## 5. 常见结论

### Q: 为什么 build 很久还没返回？

A:

- doc lane 和 kg lane 虽然并行，但 kg lane 仍可能因为 extract / resolve 占主耗时。
- 统一 build 的目标耗时是 `shared_prepare + max(doc, kg) + curriculum + publish`。

### Q: 为什么 markdown 图片已经有路径了，还要 asset registry？

A:

- markdown 图片引用是章节关联真源。
- `AssetRegistry` 只是做轻量增强：页码、类型、存在性校验。

### Q: 为什么文档不能先 publish？

A:

- 如果 docs 先 publish，而 curriculum / overview 还没 ready，就会出现半成品状态。
- 当前实现要求统一 build 成功后再切 live docs。
