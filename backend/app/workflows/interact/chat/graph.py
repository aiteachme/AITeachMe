"""Interact chat graph definition and runtime entrypoints.

This file owns the LangGraph structure plus the single-run / SSE workflow
entrypoints for the interact chat lane. Send-time chat session writes are part
of this graph; list/delete HTTP use cases stay in ``use_cases.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import Request
from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.schemas.chats import ChatSelectionContext
from app.shared.infra.llm_support.model_choices import (
    normalize_runtime_model_override,
    use_runtime_model_override,
)
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.interact.chat.lib.events import (
    InteractCompletedEvent,
    InteractFailedEvent,
    InteractRequestedEvent,
)
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.workflows.interact.chat.nodes import (
    build_finalize_chat_session_node,
    build_load_history_state_node,
    build_persist_turn_node,
    build_prompt_node,
    build_retrieve_context_node,
    build_resolve_chat_session_node,
    build_select_execution_mode_node,
    build_select_teaching_strategy_node,
    build_stream_answer_node,
)
from app.workflows.interact.chat.prompts.prompts import PROMPTS
from app.workflows.interact.chat.state import InteractWorkflowState

NODE_RESOLVE_SESSION = "resolve_chat_session"
NODE_LOAD_HISTORY = "load_history_state"
NODE_RETRIEVE_CONTEXT = "retrieve_context"
NODE_SELECT_STRATEGY = "select_teaching_strategy"
NODE_SELECT_MODE = "select_execution_mode"
NODE_BUILD_PROMPT = "build_prompt"
NODE_STREAM_ANSWER = "stream_answer"
NODE_PERSIST_TURN = "persist_turn"
NODE_FINALIZE_SESSION = "finalize_chat_session"

NODE_DISPLAY_NAMES = {
    NODE_RESOLVE_SESSION: "解析或创建会话",
    NODE_LOAD_HISTORY: "读取对话状态",
    NODE_RETRIEVE_CONTEXT: "检索学习上下文",
    NODE_SELECT_STRATEGY: "选择教学策略",
    NODE_SELECT_MODE: "选择执行模式",
    NODE_BUILD_PROMPT: "组装伴读提示词",
    NODE_STREAM_ANSWER: "流式生成回答",
    NODE_PERSIST_TURN: "保存对话轮次",
    NODE_FINALIZE_SESSION: "更新会话元信息",
}

NODE_TRACE_DETAILS = {
    NODE_RESOLVE_SESSION: {
        "description": "确认本轮要写入哪个 ChatSession；如果请求没有可用 session_id，就创建一个新会话，并通过 SSE 告知前端解析结果。",
        "reads": ["chat_session"],
        "writes": ["chat_session(create when missing)"],
        "emits": ["status:session_resolved"],
        "input_keys": ["subject_id", "user_id", "session_id", "question", "source", "model_override"],
        "output_keys": ["session_id", "session_title", "session_created"],
    },
    NODE_LOAD_HISTORY: {
        "description": "读取本会话近期消息、学科展示信息、学生整体画像、薄弱知识点和近期错题，作为个性化教学背景；这些信息只能辅助当前问题，不能抢占划选入口主题。",
        "reads": ["chat_message", "subject", "user_knowledge_state", "exam_question_result"],
        "writes": [],
        "emits": [],
        "input_keys": ["subject_id", "user_id", "session_id"],
        "output_keys": ["recent_messages", "subject_context", "weak_points", "recent_mistakes"],
    },
    NODE_RETRIEVE_CONTEXT: {
        "description": "把用户问题和划选内容合成检索 query，优先按 KnowledgeUnit/知识图谱找证据；只有图谱没有命中时才走向量检索兜底。LangSmith 内部子步骤会显示 knowledge_unit_search 和 vector_fallback_search。",
        "reads": ["knowledge_unit", "knowledge_relation", "retrieval_chunk", "vector_index"],
        "writes": [],
        "emits": [],
        "input_keys": ["subject_id", "user_id", "question", "selected_context", "selection_context"],
        "output_keys": ["retrieval_results", "contexts"],
    },
    NODE_SELECT_STRATEGY: {
        "description": "根据用户问法和是否存在划选内容，选择讲解、引导、复盘、计划或练习等教学策略。",
        "reads": [],
        "writes": [],
        "emits": [],
        "input_keys": ["question", "selected_context"],
        "output_keys": ["strategy_mode"],
    },
    NODE_SELECT_MODE: {
        "description": "决定本轮是直接单次回答，还是允许受控工具计划；划词场景默认单次回答，避免工具调用稀释入口上下文。",
        "reads": [],
        "writes": [],
        "emits": [],
        "input_keys": ["question", "selected_context", "strategy_mode", "retrieval_results"],
        "output_keys": ["execution_mode"],
    },
    NODE_BUILD_PROMPT: {
        "description": "组装最终 LLM messages：系统教学规则、划选入口上下文、检索证据、历史消息、薄弱项和近期错题都会在这里排好优先级。",
        "reads": [],
        "writes": [],
        "emits": [],
        "input_keys": [
            "subject_id",
            "subject_context",
            "question",
            "selection_context",
            "retrieval_results",
            "recent_messages",
            "weak_points",
            "recent_mistakes",
            "strategy_mode",
            "execution_mode",
        ],
        "output_keys": ["messages"],
    },
    NODE_STREAM_ANSWER: {
        "description": "调用主模型或受控工具流式生成回答，把 token 逐步推给 SSE；如果客户端断开则标记中断，不继续写库。",
        "reads": ["LLM provider"],
        "writes": [],
        "emits": ["status:answering", "token"],
        "input_keys": ["messages", "execution_mode", "retrieval_results", "model_override"],
        "output_keys": ["assistant_response", "stream_interrupted", "error"],
    },
    NODE_PERSIST_TURN: {
        "description": "在完整回答生成后，把用户消息和助手消息作为同一个 turn 写入 chat_message，并保存引用上下文和划选定位字段。",
        "reads": [],
        "writes": ["chat_message(user)", "chat_message(assistant)"],
        "emits": [],
        "input_keys": [
            "subject_id",
            "user_id",
            "session_id",
            "question",
            "assistant_response",
            "contexts",
            "source",
            "anchor_id",
            "selected_text",
            "source_chunk_id",
        ],
        "output_keys": ["turn_id"],
    },
    NODE_FINALIZE_SESSION: {
        "description": "对已完成并落库的 turn 收尾：更新会话 last_message_at，并在默认标题时生成/回退一个短标题。",
        "reads": ["chat_session", "LLM provider(optional title)"],
        "writes": ["chat_session(title)", "chat_session(last_message_at)"],
        "emits": [],
        "input_keys": ["subject_id", "user_id", "session_id", "question", "assistant_response", "turn_id"],
        "output_keys": ["session_title"],
    },
}


def build_interact_workflow_graph(
    *,
    context: WorkflowContext | None = None,
    session: Session | None = None,
    request: Request | None = None,
    emitter: SSEEventEmitter | None = None,
) -> StateGraph:
    """Build the interact workflow graph."""

    workflow_name = context.workflow_name if context is not None else "interact.chat"
    workflow = StateGraph(InteractWorkflowState)
    trace = workflow_tracer(workflow=workflow_name, lane="chat")
    workflow.add_node(
        NODE_RESOLVE_SESSION,
        _trace_interact_node(
            trace,
            NODE_RESOLVE_SESSION,
            _resolve_session_node(context=context, session=session, emitter=emitter),
        ),
        metadata=_langgraph_node_metadata(NODE_RESOLVE_SESSION),
    )
    workflow.add_node(
        NODE_LOAD_HISTORY,
        _trace_interact_node(
            trace,
            NODE_LOAD_HISTORY,
            _resolve_history_node(context=context, session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_LOAD_HISTORY),
    )
    workflow.add_node(
        NODE_RETRIEVE_CONTEXT,
        _trace_interact_node(
            trace,
            NODE_RETRIEVE_CONTEXT,
            _resolve_retrieval_node(context=context, session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_RETRIEVE_CONTEXT),
    )
    workflow.add_node(
        NODE_SELECT_STRATEGY,
        _trace_interact_node(
            trace,
            NODE_SELECT_STRATEGY,
            _resolve_strategy_node(context=context),
        ),
        metadata=_langgraph_node_metadata(NODE_SELECT_STRATEGY),
    )
    workflow.add_node(
        NODE_SELECT_MODE,
        _trace_interact_node(
            trace,
            NODE_SELECT_MODE,
            _resolve_execution_mode_node(context=context),
        ),
        metadata=_langgraph_node_metadata(NODE_SELECT_MODE),
    )
    workflow.add_node(
        NODE_BUILD_PROMPT,
        _trace_interact_node(
            trace,
            NODE_BUILD_PROMPT,
            _resolve_prompt_node(context=context),
        ),
        metadata=_langgraph_node_metadata(NODE_BUILD_PROMPT),
    )
    workflow.add_node(
        NODE_STREAM_ANSWER,
        _trace_interact_node(
            trace,
            NODE_STREAM_ANSWER,
            _resolve_stream_node(
                context=context,
                request=request,
                emitter=emitter,
            ),
        ),
        metadata=_langgraph_node_metadata(NODE_STREAM_ANSWER),
    )
    workflow.add_node(
        NODE_PERSIST_TURN,
        _trace_interact_node(
            trace,
            NODE_PERSIST_TURN,
            _resolve_persist_node(context=context, session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_PERSIST_TURN),
    )
    workflow.add_node(
        NODE_FINALIZE_SESSION,
        _trace_interact_node(
            trace,
            NODE_FINALIZE_SESSION,
            _resolve_finalize_session_node(context=context, session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_FINALIZE_SESSION),
    )

    workflow.set_entry_point(NODE_RESOLVE_SESSION)
    workflow.add_conditional_edges(
        NODE_RESOLVE_SESSION,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_LOAD_HISTORY,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_LOAD_HISTORY,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_RETRIEVE_CONTEXT,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_RETRIEVE_CONTEXT,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_SELECT_STRATEGY,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_SELECT_STRATEGY,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_SELECT_MODE,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_SELECT_MODE,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_BUILD_PROMPT,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_BUILD_PROMPT,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_STREAM_ANSWER,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_STREAM_ANSWER,
        ROUTE_AFTER_STREAM_STEP,
        {
            "continue": NODE_PERSIST_TURN,
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        NODE_PERSIST_TURN,
        ROUTE_AFTER_STANDARD_STEP,
        {
            "continue": NODE_FINALIZE_SESSION,
            "finish": END,
        },
    )
    workflow.add_edge(NODE_FINALIZE_SESSION, END)
    return workflow


def _trace_interact_node(trace, node_key: str, handler):
    details = NODE_TRACE_DETAILS[node_key]
    return trace.node(
        handler,
        name=NODE_DISPLAY_NAMES[node_key],
        description=details["description"],
        input_keys=details["input_keys"],
        output_keys=details["output_keys"],
        metadata={
            "node_key": node_key,
            "reads": details["reads"],
            "writes": details["writes"],
            "emits": details["emits"],
        },
    )


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    details = NODE_TRACE_DETAILS[node_key]
    return {
        "node_key": node_key,
        "node_display_name": NODE_DISPLAY_NAMES[node_key],
        "node_description": details["description"],
        "reads": details["reads"],
        "writes": details["writes"],
        "emits": details["emits"],
        "state_inputs": details["input_keys"],
        "state_outputs": details["output_keys"],
    }


def _named_route(fn, name: str):
    fn.__name__ = name
    fn.__qualname__ = name
    return fn


def _route_after_standard_step(state: InteractWorkflowState) -> str:
    return "finish" if state.get("error") else "continue"


def _route_after_stream_step(state: InteractWorkflowState) -> str:
    if state.get("error") or state.get("stream_interrupted"):
        return "finish"
    return "continue"


ROUTE_AFTER_STANDARD_STEP = _named_route(_route_after_standard_step, "检查是否继续")
ROUTE_AFTER_STREAM_STEP = _named_route(_route_after_stream_step, "检查是否保存对话")


def _resolve_history_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_load_history_state_node(context=context, session=session)


def _resolve_session_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
    emitter: SSEEventEmitter | None,
):
    if context is None:
        return _noop_node
    return build_resolve_chat_session_node(context=context, session=session, emitter=emitter)


def _resolve_retrieval_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_retrieve_context_node(context=context, session=session)


def _resolve_strategy_node(*, context: WorkflowContext | None):
    if context is None:
        return _noop_node
    return build_select_teaching_strategy_node(context=context)


def _resolve_execution_mode_node(*, context: WorkflowContext | None):
    if context is None:
        return _noop_node
    return build_select_execution_mode_node(context=context)


def _resolve_prompt_node(*, context: WorkflowContext | None):
    if context is None:
        return _noop_node
    return build_prompt_node(context=context)


def _resolve_stream_node(
    *,
    context: WorkflowContext | None,
    request: Request | None,
    emitter: SSEEventEmitter | None,
):
    if context is None:
        return _noop_node
    return build_stream_answer_node(context=context, request=request, emitter=emitter)


def _resolve_persist_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_persist_turn_node(context=context, session=session)


def _resolve_finalize_session_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_finalize_chat_session_node(context=context, session=session)


def _noop_node(state: InteractWorkflowState) -> InteractWorkflowState:
    return state


def get_langgraph_dev_interact_graph() -> StateGraph:
    """Create the interact graph used by ``langgraph dev``."""

    return build_interact_workflow_graph(
        context=create_langgraph_dev_context("interact.chat.langgraph_dev"),
    )


def create_interact_initial_state(
    *,
    subject_id: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source: str | None = None,
    model: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    source_chunk_id: int | None = None,
) -> InteractWorkflowState:
    """Create the initial state for one interact workflow run."""

    return {
        "subject_id": subject_id,
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
        "source": source,
        "model_override": model,
        "anchor_id": anchor_id,
        "selected_text": selected_text,
        "selected_context": selected_context,
        "selection_context": selection_context,
        "source_chunk_id": source_chunk_id,
        "stream_interrupted": False,
        "error": None,
    }


async def run_interact_workflow(
    *,
    subject_id: str,
    user_id: str,
    session_id: str | None,
    question: str,
    session: Session | None,
    request: Request,
    emitter: SSEEventEmitter,
    source: str | None = None,
    model: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    source_chunk_id: int | None = None,
    event_bus: InProcessEventBus | None = None,
) -> WorkflowResult[InteractWorkflowState]:
    """Run the interact workflow once."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(InteractRequestedEvent(subject_id=subject_id))
    model_override = normalize_runtime_model_override(model)
    context = WorkflowContext(
        workflow_name="interact.chat",
        subject_id=subject_id,
        event_bus=bus,
        metadata={
            "model_override": model_override,
        },
    )
    with use_runtime_model_override(model_override):
        result = await run_state_graph(
            workflow_name="interact.chat",
            graph_builder=lambda: build_interact_workflow_graph(
                context=context,
                session=session,
                request=request,
                emitter=emitter,
            ),
            initial_state=create_interact_initial_state(
                subject_id=subject_id,
                user_id=user_id,
                session_id=session_id,
                question=question,
                source=source,
                model=model_override,
                anchor_id=anchor_id,
                selected_text=selected_text,
                selected_context=selected_context,
                selection_context=selection_context,
                source_chunk_id=source_chunk_id,
            ),
            context=context,
        )
    if result.failed:
        await bus.publish(
            InteractFailedEvent(
                subject_id=subject_id,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            InteractFailedEvent(
                subject_id=subject_id,
                error_message=error_message,
            )
        )
        return err_result(
            "interact_workflow_failed",
            error_message,
            metadata={"subject_id": subject_id},
        )

    if not final_state.get("stream_interrupted"):
        await bus.publish(InteractCompletedEvent(subject_id=subject_id))
    return result


async def stream_chat_workflow(
    *,
    request: Request,
    session: Session | None,
    subject_id: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source: str | None = None,
    model: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    source_chunk_id: int | None = None,
    event_bus: InProcessEventBus | None = None,
) -> AsyncGenerator[str, None]:
    """Stream one interact workflow run as SSE."""

    emitter = SSEEventEmitter()
    workflow_task = asyncio.create_task(
        _execute_interact_workflow(
            emitter=emitter,
            event_bus=event_bus,
            question=question,
            request=request,
            session_id=session_id,
            source=source,
            model=model,
            anchor_id=anchor_id,
            selected_text=selected_text,
            selected_context=selected_context,
            selection_context=selection_context,
            session=session,
            source_chunk_id=source_chunk_id,
            subject_id=subject_id,
            user_id=user_id,
        )
    )
    async for payload in emitter.stream(request=request, workflow_task=workflow_task):
        yield payload


async def _execute_interact_workflow(
    *,
    emitter: SSEEventEmitter,
    event_bus: InProcessEventBus | None,
    question: str,
    request: Request,
    session_id: str | None,
    source: str | None,
    model: str | None,
    anchor_id: str | None,
    selected_text: str | None,
    selected_context: str | None,
    selection_context: ChatSelectionContext | None,
    session: Session | None,
    source_chunk_id: int | None,
    subject_id: str,
    user_id: str,
) -> None:
    try:
        result = await run_interact_workflow(
            subject_id=subject_id,
            user_id=user_id,
            session_id=session_id,
            question=question,
            session=session,
            request=request,
            emitter=emitter,
            source=source,
            model=model,
            anchor_id=anchor_id,
            selected_text=selected_text,
            selected_context=selected_context,
            selection_context=selection_context,
            source_chunk_id=source_chunk_id,
            event_bus=event_bus,
        )
        if result.failed:
            await emitter.emit_error(
                detail=result.error.detail,
                error_code=result.error.code,
            )
            return

        final_state = result.require_value()
        if final_state.get("stream_interrupted"):
            return

        await emitter.emit_done(
            turn_id=final_state["turn_id"],
            contexts=final_state.get("contexts"),
            session_id=final_state.get("session_id"),
            session_title=final_state.get("session_title"),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await emitter.emit_error(
            detail=str(exc),
            error_code="interact_runtime_failed",
        )
    finally:
        await emitter.close()


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="interact_flow",
        title="伴读对话链路",
        description="伴读式聊天链路：解析/创建会话、读取历史、检索上下文、选择教学策略、使用 primary 模型 SSE 流式回答，保存对话轮次并更新会话元信息。",
        build_graph=get_langgraph_dev_interact_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "InteractWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_interact_workflow_graph",
    "create_interact_initial_state",
    "get_langgraph_dev_interact_graph",
    "run_interact_workflow",
    "stream_chat_workflow",
]
