"""推理策略引擎。

支持：直接生成 / Chain-of-Thought / 自我反思 / 先规划后执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import structlog

from app.infra.model_router import TaskType
from app.schemas.llm import SYSTEM, USER

logger = structlog.get_logger()


# ── 类型定义 ──────────────────────────────────────────────────


class ReasoningStrategy(str, Enum):
    DIRECT = "direct"
    COT = "cot"
    REACT = "react"
    PLAN_AND_SOLVE = "plan_and_solve"
    REFLECT = "reflect"


@dataclass
class ReasoningConfig:
    strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    max_steps: int = 5


@dataclass
class ReasoningResult:
    final_answer: str
    reasoning_trace: list[str] = field(default_factory=list)


# ── 提示词工具 ────────────────────────────────────────────────

_COT_PREFIX = "请一步一步思考。先列出推理步骤，然后给出最终答案。\n\n推理步骤：\n"


def _wrap_cot(question: str) -> str:
    return f"{_COT_PREFIX}{question}\n\n最终答案："


def _parse_cot(response: str) -> tuple[str, list[str]]:
    markers = ["最终答案：", "最终答案:", "Final Answer:"]
    lines, answer = [], ""
    for line in response.strip().split("\n"):
        for m in markers:
            if m in line:
                answer = line.split(m, 1)[1].strip()
                break
        else:
            if line.strip():
                lines.append(line.strip())
    return (answer or lines.pop() if lines else response.strip()), lines


# ── 推理引擎 ──────────────────────────────────────────────────


class ReasoningEngine:
    """根据策略编排推理流程。"""

    async def reason(
        self,
        messages: list[dict],
        *,
        config: ReasoningConfig | None = None,
        task_type: TaskType = TaskType.REASONING,
    ) -> ReasoningResult:
        from app.infra.llm import acompletion

        cfg = config or ReasoningConfig()
        dispatch = {
            ReasoningStrategy.DIRECT: self._direct,
            ReasoningStrategy.COT: self._cot,
            ReasoningStrategy.REFLECT: self._reflect,
            ReasoningStrategy.PLAN_AND_SOLVE: self._plan_and_solve,
        }
        return await dispatch.get(cfg.strategy, self._direct)(messages, task_type=task_type)

    async def _direct(self, messages, *, task_type) -> ReasoningResult:
        from app.infra.llm import acompletion
        return ReasoningResult(final_answer=await acompletion(messages, task_type=task_type))

    async def _cot(self, messages, *, task_type) -> ReasoningResult:
        from app.infra.llm import acompletion
        msgs = list(messages)
        if msgs and msgs[-1].get("role") == "user":
            msgs[-1] = {"role": "user", "content": _wrap_cot(str(msgs[-1]["content"]))}
        answer, steps = _parse_cot(await acompletion(msgs, task_type=task_type))
        return ReasoningResult(final_answer=answer, reasoning_trace=steps)

    async def _reflect(self, messages, *, task_type) -> ReasoningResult:
        from app.infra.llm import acompletion
        draft = await acompletion(messages, task_type=task_type)
        refined = await acompletion([
            {"role": SYSTEM, "content": "你是严格的内容审查者。"},
            {"role": USER, "content": f"审视并改进以下回答：\n\n{draft}"},
        ], task_type=task_type)
        return ReasoningResult(final_answer=refined, reasoning_trace=[f"初稿：{draft[:100]}...", "反思修正完成"])

    async def _plan_and_solve(self, messages, *, task_type) -> ReasoningResult:
        from app.infra.llm import acompletion
        user_msg = next((str(m["content"]) for m in reversed(messages) if m.get("role") == "user"), "")
        plan = await acompletion([
            {"role": SYSTEM, "content": "请制定3-5步解决计划。"},
            {"role": USER, "content": user_msg},
        ], task_type=task_type)
        steps = [l.strip() for l in plan.split("\n") if l.strip()]
        answer = await acompletion(messages + [
            {"role": USER, "content": "按计划回答：\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))},
        ], task_type=task_type)
        return ReasoningResult(final_answer=answer, reasoning_trace=["计划："] + steps)
