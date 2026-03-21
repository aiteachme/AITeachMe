"""统一推理引擎。"""
from __future__ import annotations
import structlog
from app.core.model_router import TaskType
from app.core.reasoning.prompts import wrap_cot_prompt, parse_cot_response, build_reflect_prompt
from app.core.reasoning.strategies import ReasoningConfig, ReasoningResult, ReasoningStrategy
from app.schemas.llm import SYSTEM, USER

logger = structlog.get_logger()

class ReasoningEngine:
    async def reason(self, messages: list[dict], *, config: ReasoningConfig | None = None,
                     tools: list[dict] | None = None, task_type: TaskType = TaskType.REASONING) -> ReasoningResult:
        from app.core.llm import acompletion
        cfg = config or ReasoningConfig()
        dispatch = {
            ReasoningStrategy.DIRECT: self._direct, ReasoningStrategy.COT: self._cot,
            ReasoningStrategy.REFLECT: self._reflect, ReasoningStrategy.PLAN_AND_SOLVE: self._plan_and_solve,
        }
        fn = dispatch.get(cfg.strategy, self._direct)
        return await fn(messages, config=cfg, task_type=task_type)

    async def _direct(self, messages, *, config, task_type) -> ReasoningResult:
        from app.core.llm import acompletion
        return ReasoningResult(final_answer=await acompletion(messages, task_type=task_type))

    async def _cot(self, messages, *, config, task_type) -> ReasoningResult:
        from app.core.llm import acompletion
        msgs = list(messages)
        if msgs and msgs[-1].get("role") == "user":
            msgs[-1] = {"role": "user", "content": wrap_cot_prompt(str(msgs[-1]["content"]))}
        raw = await acompletion(msgs, task_type=task_type)
        answer, steps = parse_cot_response(raw)
        return ReasoningResult(final_answer=answer, reasoning_trace=steps)

    async def _reflect(self, messages, *, config, task_type) -> ReasoningResult:
        from app.core.llm import acompletion
        draft = await acompletion(messages, task_type=task_type)
        prompt = build_reflect_prompt(draft, "准确性、完整性、来源支撑、是否回答了问题")
        refined = await acompletion([{"role": SYSTEM, "content": "你是严格的教学内容审查者。"},
                                     {"role": USER, "content": prompt}], task_type=task_type)
        return ReasoningResult(final_answer=refined, reasoning_trace=[f"初稿：{draft[:200]}...", "已完成反思修正"])

    async def _plan_and_solve(self, messages, *, config, task_type) -> ReasoningResult:
        from app.core.llm import acompletion
        user_msg = next((str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"), "")
        plan = await acompletion([{"role": SYSTEM, "content": "你是善于分析和规划的教学助手。"},
                                  {"role": USER, "content": f"请针对以下问题制定3-5步计划：\n\n{user_msg}"}], task_type=task_type)
        steps = [l.strip() for l in plan.split("\n") if l.strip()]
        answer = await acompletion(list(messages) + [{"role": USER, "content": f"按计划回答：\n{''.join(f'{i+1}. {s}\n' for i, s in enumerate(steps))}"}], task_type=task_type)
        return ReasoningResult(final_answer=answer, reasoning_trace=["计划："] + steps)

    async def plan(self, goal: str, context: str = "", *, max_steps: int = 10) -> list[str]:
        from app.core.llm import acompletion
        result = await acompletion([{"role": SYSTEM, "content": "你是教学规划助手。"},
                                    {"role": USER, "content": f"将目标分解为{max_steps}步以内：\n\n目标：{goal}\n" + (f"背景：{context}\n" if context else "")}], task_type=TaskType.REASONING)
        return [l.strip() for l in result.split("\n") if l.strip()]
