"""Central model policy for Interact chat LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.shared.infra.settings import get_settings
from app.workflows.common.model_policy import ProviderNativeToolPolicy, compact_metadata

InteractModelSlot = Literal["light", "primary", "reason"]
INTERACT_MODEL_SELECTOR: InteractModelSlot = "primary"


class InteractModelStep(str, Enum):
    RESPONSE_STREAM = "chat.response_stream"
    SESSION_TITLE = "chat.session_title"
    HOME_INTAKE_INTENT = "chat.home_intake_intent"


@dataclass(frozen=True)
class InteractModelPolicy:
    step: InteractModelStep
    call_type: Literal["stream", "text"]
    model: InteractModelSlot
    max_tokens: int | None = None
    timeout_s: int | None = None
    max_retries: int = 3
    temperature: float | None = None
    provider_native_tools: ProviderNativeToolPolicy = field(default_factory=ProviderNativeToolPolicy.disabled)
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        kwargs["max_retries"] = self.max_retries
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def llm_kwargs(self) -> dict[str, object]:
        """Return LLM helper kwargs used by shared infra wrappers."""

        kwargs: dict[str, object] = {}
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        kwargs["max_retries"] = self.max_retries
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def metadata(self, *, model_override: str | None = None) -> dict[str, object]:
        metadata: dict[str, object] = {
            "chat_model_step": self.step.value,
            "chat_model_slot": self.model,
            "chat_call_type": self.call_type,
            "chat_max_tokens": self.max_tokens,
            "chat_timeout_s": self.timeout_s,
            "chat_max_retries": self.max_retries,
            **self.provider_native_tools.metadata(prefix="chat_provider_native"),
        }
        resolved_override = normalize_runtime_model_override(model_override)
        if resolved_override:
            metadata["chat_model_override"] = resolved_override
        return metadata

    def provider_native_tool_requests(
        self,
        *,
        web_search: bool = False,
        file_search: bool = False,
    ) -> list[dict[str, object]]:
        return self.provider_native_tools.build(
            settings=get_settings(),
            web_search=web_search,
            file_search=file_search,
        )

    def completion_kwargs_with_metadata(
        self,
        *,
        model_override: str | None = None,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(
            extra_metadata,
            metadata,
            self.metadata(model_override=model_override),
        )
        return kwargs


_POLICIES: dict[InteractModelStep, InteractModelPolicy] = {
    InteractModelStep.RESPONSE_STREAM: InteractModelPolicy(
        step=InteractModelStep.RESPONSE_STREAM,
        call_type="stream",
        model=INTERACT_MODEL_SELECTOR,
        max_tokens=12000,
        timeout_s=240,
        temperature=0.7,
        provider_native_tools=ProviderNativeToolPolicy(
            web_search="settings",
            file_search="settings",
        ),
        note="伴读最终回答可长可短，给足输出空间避免流式回答被过早截断。",
    ),
    InteractModelStep.SESSION_TITLE: InteractModelPolicy(
        step=InteractModelStep.SESSION_TITLE,
        call_type="text",
        model="light",
        max_tokens=128,
        timeout_s=240,
        temperature=0.2,
        note="会话标题仍是短输出，但给模型留出清洗前的冗余空间。",
    ),
    InteractModelStep.HOME_INTAKE_INTENT: InteractModelPolicy(
        step=InteractModelStep.HOME_INTAKE_INTENT,
        call_type="text",
        model="light",
        max_tokens=1800,
        timeout_s=240,
        temperature=0.1,
        note="首页入口需要 JSON 意图和可直接展示的追问文案。",
    ),
}


def get_interact_model_policy(step: InteractModelStep | str) -> InteractModelPolicy:
    resolved_step = step if isinstance(step, InteractModelStep) else InteractModelStep(str(step))
    return _POLICIES[resolved_step]


def interact_completion_kwargs(step: InteractModelStep | str) -> dict[str, object]:
    return get_interact_model_policy(step).completion_kwargs()


def interact_llm_kwargs(step: InteractModelStep | str) -> dict[str, object]:
    return get_interact_model_policy(step).llm_kwargs()


def interact_completion_kwargs_with_metadata(
    step: InteractModelStep | str,
    *,
    model_override: str | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_interact_model_policy(step).completion_kwargs_with_metadata(
        model_override=model_override,
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "INTERACT_MODEL_SELECTOR",
    "InteractModelPolicy",
    "InteractModelSlot",
    "InteractModelStep",
    "ProviderNativeToolPolicy",
    "get_interact_model_policy",
    "interact_completion_kwargs",
    "interact_completion_kwargs_with_metadata",
    "interact_llm_kwargs",
]
