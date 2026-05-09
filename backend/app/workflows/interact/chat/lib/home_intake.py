"""Homepage intake conversation helpers.

This module handles the global homepage chat entry where the assistant must
understand intent, ask follow-up questions, and only create a course after the
user confirms a pending creation plan.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.agent_tools.catalog import build_agent_tool_catalog
from app.agent_tools.global_scope.course_management import create_course_from_home_intake_tool
from app.agent_tools.policy import AgentToolPolicyRequest
from app.models import ChatSession
from app.repositories.chats_repo import get_chat_session
from app.shared.infra.database import managed_session
from app.shared.infra.llm_support import acompletion
from app.utils.course import GLOBAL_COURSE, is_global_course
from app.workflows.interact.chat.lib.model_policy import (
    InteractModelStep,
    interact_completion_kwargs_with_metadata,
)
from app.workflows.interact.chat.lib.types import RecentMessage
from app.workflows.interact.chat.state import InteractWorkflowState

logger = structlog.get_logger(__name__)

HOME_INTAKE_SOURCE = "home_intake"
_GLOBAL_HOME_INTAKE_SOURCES = frozenset({"", "home", "global_assistant", HOME_INTAKE_SOURCE})
_CREATE_INTENT_KEYWORDS = (
    "创建",
    "新建",
    "构建",
    "生成",
    "规划",
    "建一个",
    "做一个",
    "学习空间",
    "知识库",
)
_CONFIRM_KEYWORDS = (
    "确认",
    "确定",
    "可以",
    "开始",
    "创建吧",
    "新建吧",
    "构建吧",
    "没问题",
    "好的",
    "ok",
    "yes",
)
_CANCEL_KEYWORDS = ("取消", "先不用", "不要", "别创建", "不创建", "算了")


@dataclass(frozen=True)
class HomeIntakeResult:
    assistant_response: str
    client_actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class HomeIntakeIntent:
    intent: str
    assistant_reply: str
    course_name: str = ""
    description: str = ""
    user_intent: str = ""
    planner_prompt: str = ""
    ready_to_create: bool = False


def is_home_intake_source(source: str | None) -> bool:
    return (source or "").strip() == HOME_INTAKE_SOURCE


def should_use_home_intake_flow(
    *,
    scene: str | None = None,
    source: str | None,
    course_id: str | None,
    question: str | None,
    recent_messages: list[RecentMessage] | None = None,
) -> bool:
    scene_value = (scene or "").strip()
    if scene_value == HOME_INTAKE_SOURCE:
        return True
    if scene_value and scene_value != "global_assistant":
        return False
    if is_home_intake_source(source):
        return True
    if not is_global_course(course_id):
        return False
    if (source or "").strip() not in _GLOBAL_HOME_INTAKE_SOURCES:
        return False
    return (
        _looks_like_create_intent(question or "")
        or _looks_like_confirmation(question or "")
        or _looks_like_cancel(question or "")
        or _recent_assistant_asked_for_creation_detail(recent_messages or [])
    )


async def run_home_intake_turn(
    state: InteractWorkflowState,
    *,
    background_task_registry: object | None = None,
    tool_event_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> HomeIntakeResult:
    """Run one homepage intake turn without exposing write tools by default."""

    question = str(state.get("question") or "").strip()
    file_ids = list(dict.fromkeys(str(item).strip() for item in state.get("attached_file_ids", []) if str(item).strip()))
    session_id = str(state.get("session_id") or "").strip()
    user_id = str(state.get("user_id") or "local")
    pending_action = _load_pending_action(
        session_id=session_id,
        user_id=user_id,
    )

    if pending_action and _looks_like_cancel(question):
        _save_pending_action(session_id=session_id, user_id=user_id, pending_action=None)
        return HomeIntakeResult("好的，先不创建学科。你可以继续告诉我想整理什么资料，或者先随便问我。")

    if pending_action and _looks_like_confirmation(question):
        return await _create_from_pending_action(
            pending_action,
            current_file_ids=file_ids,
            session_id=session_id,
            user_id=user_id,
            model=str(state.get("model_override") or ""),
            background_task_registry=background_task_registry,
            tool_event_handler=tool_event_handler,
        )

    intent = await _classify_home_intake_intent(
        question=question,
        attached_file_ids=file_ids,
        recent_messages=state.get("recent_messages", []),
        pending_action=pending_action,
        model=str(state.get("model_override") or "") or None,
    )
    if intent.intent != "create_course":
        _save_pending_action(session_id=session_id, user_id=user_id, pending_action=None)
        return HomeIntakeResult(
            intent.assistant_reply
            or "我在。你可以先问问题、整理资料，也可以告诉我想创建什么学科。"
        )

    if not intent.ready_to_create:
        _save_pending_action(session_id=session_id, user_id=user_id, pending_action=None)
        return HomeIntakeResult(
            intent.assistant_reply
            or "可以，我先确认一下：你想创建哪门学科？希望它主要帮你解决什么学习目标？"
        )

    pending = _build_pending_action(intent, file_ids=file_ids)
    _save_pending_action(session_id=session_id, user_id=user_id, pending_action=pending)
    return HomeIntakeResult(_build_confirmation_reply(pending))


async def _classify_home_intake_intent(
    *,
    question: str,
    attached_file_ids: list[str],
    recent_messages: list[RecentMessage],
    pending_action: dict[str, Any] | None,
    model: str | None,
) -> HomeIntakeIntent:
    if not question and attached_file_ids:
        return HomeIntakeIntent(
            intent="create_course",
            assistant_reply="资料已经准备好了。你想用这些资料创建哪门学科？也可以补充一下学习目标。",
            ready_to_create=False,
        )
    if (
        _recent_assistant_asked_for_creation_detail(recent_messages)
        and not _looks_like_cancel(question)
        and not _looks_like_confirmation(question)
        and _looks_like_creation_detail_answer(question)
    ):
        course_name = _guess_course_name(question)
        return HomeIntakeIntent(
            intent="create_course",
            assistant_reply="",
            ready_to_create=True,
            course_name=course_name,
            description=f"围绕「{course_name}」创建的学习空间。",
            user_intent=question,
            planner_prompt=f"为「{course_name}」构建系统学习路径。",
        )
    try:
        tool_catalog = build_agent_tool_catalog(
            AgentToolPolicyRequest(
                scene=HOME_INTAKE_SOURCE,
                source=HOME_INTAKE_SOURCE,
                course_id=GLOBAL_COURSE,
                allow_write_tools=False,
            ),
            active_tool_names=[],
        )
        raw = await acompletion(
            _build_intent_messages(
                question=question,
                attached_file_ids=attached_file_ids,
                recent_messages=recent_messages,
                pending_action=pending_action,
                tool_catalog=tool_catalog,
            ),
            **interact_completion_kwargs_with_metadata(
                InteractModelStep.HOME_INTAKE_INTENT,
                model_override=model,
                extra_metadata={
                    "substep": "interact.chat.home_intake_intent",
                    "attached_file_count": len(attached_file_ids),
                    "has_pending_action": pending_action is not None,
                },
            ),
        )
        payload = _extract_json_object(raw)
        if payload:
            return _intent_from_payload(payload, question=question, attached_file_ids=attached_file_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("home_intake_intent_llm_failed", error=str(exc))
    return _fallback_intent(question=question, attached_file_ids=attached_file_ids)


def _build_intent_messages(
    *,
    question: str,
    attached_file_ids: list[str],
    recent_messages: list[RecentMessage],
    pending_action: dict[str, Any] | None,
    tool_catalog: str | None = None,
) -> list[dict[str, str]]:
    recent_text = "\n".join(
        f"{message.role}: {message.content[:240]}"
        for message in recent_messages[-6:]
    )
    return [
        {
            "role": "system",
            "content": (
                "你是 AITeachMe 首页入口的意图识别助手。"
                "只判断当前用户是否想创建/构建新的学科或课程。"
                "如果只是闲聊、咨询、问怎么用、或信息不足，不要创建。"
                "必须输出一个 JSON 对象，不要输出 Markdown。"
                "字段：intent=create_course|chat，ready_to_create=true|false，"
                "course_name，description，user_intent，planner_prompt，assistant_reply。"
                "当且仅当用户明确表达创建/构建学科且目标足够清楚时 ready_to_create=true；"
                "否则 assistant_reply 用自然中文追问或回答。"
            ) + _format_intent_tool_catalog(tool_catalog),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "attached_file_count": len(attached_file_ids),
                    "recent_messages": recent_text,
                    "pending_action": pending_action,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _format_intent_tool_catalog(tool_catalog: str | None) -> str:
    catalog = (tool_catalog or "").strip()
    if not catalog:
        return ""
    return (
        "\n\nRegistered agent tool catalog:\n"
        "Use this catalog as the source of truth when answering capability/tool questions in assistant_reply. "
        "Do not invent tools. Tools marked `available_by_policy` describe supported capabilities but may not be callable in this exact turn. "
        "Tools marked `requires_user_confirmation` can be prepared after explicit user confirmation, "
        "but must not be reported as completed until the tool succeeds.\n"
        f"{catalog}"
    )


def _intent_from_payload(
    payload: dict[str, Any],
    *,
    question: str,
    attached_file_ids: list[str],
) -> HomeIntakeIntent:
    intent = str(payload.get("intent") or "chat").strip()
    ready_to_create = bool(payload.get("ready_to_create"))
    if intent == "create_course" and ready_to_create and not _has_enough_creation_detail(payload, question, attached_file_ids):
        ready_to_create = False
    return HomeIntakeIntent(
        intent="create_course" if intent == "create_course" else "chat",
        ready_to_create=ready_to_create,
        course_name=str(payload.get("course_name") or "").strip(),
        description=str(payload.get("description") or "").strip(),
        user_intent=str(payload.get("user_intent") or "").strip(),
        planner_prompt=str(payload.get("planner_prompt") or question).strip(),
        assistant_reply=str(payload.get("assistant_reply") or "").strip(),
    )


def _fallback_intent(*, question: str, attached_file_ids: list[str]) -> HomeIntakeIntent:
    if not _looks_like_create_intent(question):
        return HomeIntakeIntent(
            intent="chat",
            assistant_reply="我在。你可以先问我问题，也可以告诉我想学习的方向；如果要创建学科，我会先和你确认再开始。",
        )
    if not _has_enough_creation_detail({}, question, attached_file_ids):
        return HomeIntakeIntent(
            intent="create_course",
            ready_to_create=False,
            assistant_reply="可以创建，不过我还需要一个更明确的方向：这门学科叫什么？你希望它重点帮你解决什么学习目标？",
        )
    course_name = _guess_course_name(question)
    return HomeIntakeIntent(
        intent="create_course",
        ready_to_create=True,
        course_name=course_name,
        description=f"围绕「{course_name}」创建的学习空间。",
        user_intent=question,
        planner_prompt=question,
    )


def _build_pending_action(intent: HomeIntakeIntent, *, file_ids: list[str]) -> dict[str, Any]:
    course_name = intent.course_name or _guess_course_name(intent.planner_prompt or intent.user_intent)
    planner_prompt = intent.planner_prompt or intent.user_intent or course_name
    return {
        "tool": "create_course_from_home_intake",
        "name": course_name,
        "description": intent.description,
        "user_intent": intent.user_intent or planner_prompt,
        "planner_prompt": planner_prompt,
        "attached_file_ids": file_ids,
    }


def _build_confirmation_reply(pending_action: dict[str, Any]) -> str:
    name = str(pending_action.get("name") or "新学科")
    user_intent = str(pending_action.get("user_intent") or pending_action.get("planner_prompt") or "").strip()
    file_count = len(list(pending_action.get("attached_file_ids") or []))
    file_text = f"，并关联当前选择的 {file_count} 份资料" if file_count else ""
    lines = [
        f"我理解你是想创建「{name}」这个学科{file_text}。",
    ]
    if user_intent:
        lines.append(f"学习目标：{user_intent}")
    lines.append("如果没问题，回复“确认创建”，我再正式创建并打开构建规划页。")
    return "\n".join(lines)


async def _create_from_pending_action(
    pending_action: dict[str, Any],
    *,
    current_file_ids: list[str],
    session_id: str,
    user_id: str,
    model: str,
    background_task_registry: object | None,
    tool_event_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> HomeIntakeResult:
    file_ids = list(
        dict.fromkeys(
            [
                *[str(item).strip() for item in list(pending_action.get("attached_file_ids") or [])],
                *current_file_ids,
            ]
        )
    )
    start = time.monotonic()
    await _emit_tool_event(
        tool_event_handler,
        phase="started",
        tool_name="create_course_from_home_intake",
        tool_call_id="home_intake_create_course",
        argument_names=["name", "description", "user_intent", "planner_prompt"],
    )
    try:
        result = await create_course_from_home_intake_tool(
            name=str(pending_action.get("name") or "新学科"),
            description=str(pending_action.get("description") or ""),
            user_intent=str(pending_action.get("user_intent") or ""),
            planner_prompt=str(pending_action.get("planner_prompt") or ""),
            user_id=user_id,
            attached_file_ids=file_ids,
            background_task_registry=background_task_registry,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = round(time.monotonic() - start, 3)
        await _emit_tool_event(
            tool_event_handler,
            phase="failed",
            tool_name="create_course_from_home_intake",
            tool_call_id="home_intake_create_course",
            elapsed_s=elapsed,
            success=False,
            error=str(exc),
        )
        logger.warning("home_intake_create_course_failed", error=str(exc))
        return HomeIntakeResult(f"创建学科时遇到问题：{exc}")

    elapsed = round(time.monotonic() - start, 3)
    await _emit_tool_event(
        tool_event_handler,
        phase="completed",
        tool_name="create_course_from_home_intake",
        tool_call_id="home_intake_create_course",
        elapsed_s=elapsed,
        success=True,
    )
    _save_pending_action(session_id=session_id, user_id=user_id, pending_action=None)
    data = result.get("data") if isinstance(result, dict) else {}
    course_name = str((data or {}).get("course_name") or pending_action.get("name") or "新学科")
    actions = list(result.get("client_actions") or []) if isinstance(result, dict) else []
    if model:
        for action in actions:
            payload = action.get("payload")
            if isinstance(payload, dict):
                payload["model"] = model
    return HomeIntakeResult(
        assistant_response=f"已创建「{course_name}」，正在打开构建规划页。",
        client_actions=actions,
    )


async def _emit_tool_event(
    handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
    **payload: Any,
) -> None:
    if handler is None:
        return
    result = handler(payload)
    if hasattr(result, "__await__"):
        await result


def _load_pending_action(*, session_id: str, user_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with managed_session() as session:
        record = get_chat_session(
            session,
            course_id=GLOBAL_COURSE,
            user_id=user_id,
            session_id=session_id,
        )
        return _pending_from_session(record)


def _save_pending_action(
    *,
    session_id: str,
    user_id: str,
    pending_action: dict[str, Any] | None,
) -> None:
    if not session_id:
        return
    with managed_session() as session:
        record = get_chat_session(
            session,
            course_id=GLOBAL_COURSE,
            user_id=user_id,
            session_id=session_id,
        )
        if record is None:
            return
        meta = dict(record.meta_json or {})
        home_meta = dict(meta.get("home_intake") or {})
        if pending_action:
            home_meta["pending_action"] = pending_action
        else:
            home_meta.pop("pending_action", None)
        if home_meta:
            meta["home_intake"] = home_meta
        else:
            meta.pop("home_intake", None)
        record.meta_json = meta
        session.add(record)
        session.commit()


def _pending_from_session(record: ChatSession | None) -> dict[str, Any] | None:
    if record is None or not isinstance(record.meta_json, dict):
        return None
    home_meta = record.meta_json.get("home_intake")
    if not isinstance(home_meta, dict):
        return None
    pending = home_meta.get("pending_action")
    return pending if isinstance(pending, dict) else None


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _looks_like_create_intent(text: str) -> bool:
    normalized = str(text or "").casefold()
    return any(keyword.casefold() in normalized for keyword in _CREATE_INTENT_KEYWORDS)


def _looks_like_confirmation(text: str) -> bool:
    normalized = str(text or "").casefold().strip()
    return any(keyword.casefold() in normalized for keyword in _CONFIRM_KEYWORDS)


def _looks_like_cancel(text: str) -> bool:
    normalized = str(text or "").casefold().strip()
    return any(keyword.casefold() in normalized for keyword in _CANCEL_KEYWORDS)


def _recent_assistant_asked_for_creation_detail(recent_messages: list[RecentMessage]) -> bool:
    for message in reversed(recent_messages[-4:]):
        if message.role != "assistant":
            continue
        content = re.sub(r"\s+", "", message.content)
        if not content:
            return False
        mentions_creation = any(keyword in content for keyword in ("创建", "新建", "构建", "学科", "课程", "学习空间"))
        asks_for_detail = any(
            keyword in content
            for keyword in (
                "想创建哪",
                "创建哪",
                "创建什么",
                "叫什么",
                "学习目标",
                "学习方向",
                "重点帮你解决",
                "我先确认一下",
            )
        )
        return mentions_creation and asks_for_detail
    return False


def _looks_like_creation_detail_answer(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "")).strip()
    if len(normalized) < 2:
        return False
    vague_answers = {"不知道", "随便", "都行", "你看着办", "不清楚", "还没想好", "没有"}
    if normalized in vague_answers:
        return False
    return not normalized.endswith(("?", "？"))


def _has_enough_creation_detail(
    payload: dict[str, Any],
    question: str,
    attached_file_ids: list[str],
) -> bool:
    course_name = str(payload.get("course_name") or "").strip()
    user_intent = str(payload.get("user_intent") or payload.get("planner_prompt") or question or "").strip()
    normalized = re.sub(r"\s+", "", user_intent)
    vague_phrases = {"创建学科", "新建学科", "创建课程", "新建课程", "开始构建", "帮我创建", "帮我新建"}
    if course_name and len(course_name) >= 2:
        return True
    if attached_file_ids and len(normalized) >= 4 and normalized not in vague_phrases:
        return True
    return len(normalized) >= 6 and normalized not in vague_phrases


def _guess_course_name(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return "新学科"
    patterns = [
        r"(?:创建|新建|构建|生成|规划)(?:一个|一门|个|门)?(.{2,24}?)(?:学科|课程|知识库|学习空间)",
        r"(?:学习|复习|掌握|整理)(.{2,18})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            candidate = _clean_course_name(match.group(1))
            if candidate:
                return candidate[:20]
    return _clean_course_name(normalized)[:20] or "新学科"


def _clean_course_name(value: str) -> str:
    cleaned = re.sub(r"[，。！？；:：,.!?;]+", " ", str(value or ""))
    cleaned = re.sub(r"(帮我|请|我想|我要|希望|用这些资料|根据资料|来|的)$", "", cleaned).strip()
    return cleaned.strip("「」《》“”\"' ")
