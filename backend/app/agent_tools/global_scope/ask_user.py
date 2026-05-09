"""Global user-question agent tools."""

from __future__ import annotations

from typing import Any

from app.agent_tools.result import AgentToolResult, ClientAction
from app.shared.infra.tools.decorator import tool


@tool(
    "ask_user_options",
    "Ask the user one clarifying question with selectable options.",
    usage=(
        "Use when the next step depends on a user choice and you can offer 2-6 clear options. "
        "Call this instead of burying choices in plain text. The client will render option buttons. "
        "Do not treat the selected option as known until the user replies."
    ),
    tags=["global", "interaction", "clarify"],
    source="agent_tools.global_scope",
    risk_level="low",
    scopes=["user:ask"],
)
async def ask_user_options_tool(
    question: str,
    options: list,
    allow_custom_response: bool = True,
) -> dict[str, object]:
    """Return a client action that renders a user-choice prompt."""

    cleaned_question = _clip_text(question, 240)
    normalized_options = _normalize_options(options)
    payload = {
        "question": cleaned_question,
        "options": normalized_options,
        "allow_custom_response": bool(allow_custom_response),
    }
    return AgentToolResult(
        ok=True,
        message=f"Asked user: {cleaned_question}",
        data=payload,
        client_actions=[
            ClientAction(
                type="ask_user_options",
                payload=payload,
            )
        ],
        audit={"tool": "ask_user_options"},
    ).to_dict()


def _normalize_options(options: list) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, raw_option in enumerate(options or [], start=1):
        if isinstance(raw_option, dict):
            label = _clip_text(raw_option.get("label") or raw_option.get("text") or raw_option.get("value"), 80)
            value = _clip_text(raw_option.get("value") or label, 160)
            description = _clip_text(raw_option.get("description") or raw_option.get("detail"), 160)
            option_id = _clip_text(raw_option.get("id") or f"option_{index}", 48)
        else:
            label = _clip_text(raw_option, 80)
            value = label
            description = ""
            option_id = f"option_{index}"
        if not label:
            continue
        normalized.append(
            {
                "id": option_id or f"option_{index}",
                "label": label,
                "value": value or label,
                "description": description,
            }
        )
        if len(normalized) >= 6:
            break
    if len(normalized) < 2:
        raise ValueError("ask_user_options requires 2 to 6 non-empty options.")
    return normalized


def _clip_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "..."


ask_user_options_tool.__tool_definition__.parameters = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "The concise question to ask the user.",
        },
        "options": {
            "type": "array",
            "description": "2-6 selectable options. Each item may be a string or an object with label, value, and optional description.",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "value": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["label"],
                    },
                ]
            },
        },
        "allow_custom_response": {
            "type": "boolean",
            "description": "Whether the user may answer with free text instead of one option.",
        },
    },
    "required": ["question", "options"],
}
