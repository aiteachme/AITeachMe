# 17. Infra 模块化收口笔记

最后更新：2026-04-15

这份笔记记录最近一轮 `backend/app/shared/infra/` 调整背后的设计理由，方便后续继续重构时不中断上下文。

## 1. 本轮已落地的结构调整

- `database.py` -> `database/`
  保持 `app.shared.infra.database` 导入面不变，内部改成包，为后续继续拆 `engine / session / vector helpers` 预留空间。
- `mcp.py` -> `mcp/`
  先变成包，当前仍以 `manager.py` 为主；后续可以继续拆 transport、client/session、tool bridge。
- `embedding.py` -> `embedding/`
  `api.py` 作为 canonical embedding 调用入口；`llamaindex.py` 放 LlamaIndex 的 embedding 适配。
- `search/llamaindex_adapter/`
  继续只保留 search 语义更强的部分：vector store、retriever、reranker。
- `llm_support/context_window.py`
  保留在 LLM 层，但策略已经从“每段硬裁剪”改成“总预算内软分配”。

## 2. 关键设计判断

### 2.1 `database/` 和 `mcp/` 不该放在同一个目录

虽然两者都属于 infra，但语义完全不同：

- `database/` 是应用运行时持久化底座
- `mcp/` 是外部协议 / 工具接入

如果把它们并到一个公共目录，只会形成新的“杂项基础设施层”。更合理的方向是：

- `database/` 独立作为 runtime persistence base
- `mcp/` 未来往 `tools/` 或单独 integrations 子层靠拢

### 2.2 `embedding/` 不等于 `search/`

本地代码里真正重复的不是“embedding 调用”，而是“embedding 语义的归属”：

- `aembed_texts()` 是 provider-facing 能力
- LlamaIndex 的 `BaseEmbedding` 适配，本质上仍是 embedding 语义
- vector store / retriever / reranker 才是 search 语义

因此本轮的判断是：

- embedding 调用和 embedding 框架适配归 `embedding/`
- 检索框架集成的其余部分继续归 `search/llamaindex_adapter/`
- 先不急着创建 `embedding/adapters/`，等出现第二种框架适配再拆，避免只有一个适配器时过度分层
- `ATMEmbedding` 不再由 `search` 包重导出，避免边界在导入面上重新混回去

### 2.3 `context_window` 不能用硬上限把上下文锁死

之前的策略风险在于：

- retrieval、history、user query 分别被卡死在固定上限
- 某一段没用满时，预算不会回流给其他段
- 超长最后一条消息可能整条被丢掉

本轮改成软预算的原则是：

- 保留 section target cap 作为默认目标
- 总输入预算由 `total - reserved_for_output` 控制
- 空出来的预算可以回流给 user / retrieval / history / system
- 超长最后一条消息至少保留一个截断版本
- `interact` prompt 组装入口不再先按 `chat_history` 预裁历史消息，而是把完整历史交给预算器统一收口

如果未来只有 `interact` 使用这套逻辑，可以考虑再下沉；但只要它继续承担“LLM 输入组织”职责，就不应回到根目录级杂项文件。

## 3. 仍待继续收口的点

- `strategies.py`
  当前业务语义过重，更像 interact / teaching 层能力。
- `reasoning.py`
  当前抽象尚未真正进入主链，后续要么正式落地，要么收缩掉。
- `agent_loop.py`
  更像 agent runtime，后续可考虑进入 `llm_support/agents` 或类似子层。
- `events.py`
  当前已经是一个带存储的事件日志子系统，不再只是“事件类型定义”。

## 4. 参考过的开源框架思路

这轮的组织方式主要参考了三类成熟项目的分层习惯：

- OpenHands
  倾向把 reasoning loop、LLM integration、MCP/extensibility 放进清晰的 SDK/package 边界，而不是根目录单文件堆叠。
  参考：`https://docs.openhands.dev/sdk/arch/sdk`
- Haystack
  倾向把 prompt / chat message 组织能力放在 builder 组件层，而不是到处散落 helper。
  参考：`https://docs.haystack.deepset.ai/docs/chatpromptbuilder`
- LlamaIndex
  把 embeddings 视为 model-layer 抽象，并允许通过自定义 adapter 挂接到底层实现。
  参考：`https://developers.llamaindex.ai/python/framework/module_guides/models/embeddings/`

这些参考并不是要求完全照搬，而是帮助我们在本项目里坚持几个方向：

- 底层能力和框架适配分开
- 运行时持久化和外部协议接入分开
- prompt / context / reasoning / agent loop 不要全部平铺在 infra 根目录

## 5. 当前推荐的下一步优先级

1. 先决定 `strategies.py` 的归位位置。
2. 再判断 `reasoning.py` 是真正要进入主链，还是应当收缩。
3. 再把 `agent_loop.py` 从根目录整理进 agent runtime 子层。
4. 最后再考虑 `events.py` 是否拆成 event log 子包。
