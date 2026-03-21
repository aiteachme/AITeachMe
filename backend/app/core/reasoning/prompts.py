"""推理提示词模板（CoT、ReAct、Reflect）。"""
from __future__ import annotations

# ── Chain-of-Thought ──
COT_PREFIX = "请一步一步思考这个问题。先列出你的推理步骤，然后在最后给出最终答案。\n\n推理步骤：\n"
COT_SUFFIX = "\n\n最终答案："

def wrap_cot_prompt(question: str) -> str:
    return f"{COT_PREFIX}{question}{COT_SUFFIX}"

def parse_cot_response(response: str) -> tuple[str, list[str]]:
    lines = response.strip().split("\n")
    markers = ["最终答案：", "最终答案:", "Final Answer:"]
    reasoning, answer = [], ""
    for line in lines:
        found = False
        for m in markers:
            if m in line:
                answer = line.split(m, 1)[1].strip()
                found = True; break
        if not found and line.strip():
            reasoning.append(line.strip())
    if not answer:
        answer = reasoning.pop() if reasoning else response.strip()
    return answer, reasoning

# ── ReAct ──
REACT_SYSTEM_PROMPT = """你是一个能够思考和使用工具的助手。
对于每一步：1. Thought：分析当前情况 2. Action：调用工具 3. Observation：观察结果
当信息足够时直接给出最终回答。每次只执行一个行动。"""

def format_react_step(step_num: int, thought: str, action: str | None = None, observation: str | None = None) -> str:
    parts = [f"步骤 {step_num}：", f"  思考：{thought}"]
    if action: parts.append(f"  行动：{action}")
    if observation: parts.append(f"  观察：{observation}")
    return "\n".join(parts)

# ── Reflect ──
REFLECT_PROMPT = "请审视你之前的回答并进行自我评估：\n\n之前的回答：\n{draft}\n\n评估标准：\n{criteria}\n\n请指出不足并给出改进后的最终回答。"

def build_reflect_prompt(draft: str, criteria: str) -> str:
    return REFLECT_PROMPT.format(draft=draft, criteria=criteria)
