"""Prompt for content-only repairs of numbered chapter-end questions."""

from __future__ import annotations

import json

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.prompts.unit_test_contract import UNIT_TEST_STRUCTURED_CONTENT_CONTRACT


def build_unit_test_question_patch_messages(
    *, chapter_title: str, actions: list[dict], questions: dict[int, str],
    quantity_contract: dict, related_markdown_context: str, previous_rejection: str,
) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": (
            "你是 AITeachMe 的题目内容修补器，只输出合法 JSON。"
            "仅为复核指出的错误返回必要题号的完整结构化替换内容；其余题目由程序逐字保留，禁止顺手重写。"
            "patches 每项包含 question_number（已有 Q 题号的整数）与 item，"
            "item 包含 type、difficulty、target、stem、options、answer、basis。"
            "不要返回整份测试、Markdown 题答块或题组标题，不新增、删除、交换题号。"
            "每题独立复算后再输出，核验题干条件、每步解析、答案、单位及整数等实际限制；"
            "不能只让方程算式成立而忽略题设情境矛盾。你负责直接输出已完成纠错的最终题目，不依赖后续模型复审。"
            "covered_action_ids 列出已完整解决的 repair_action_key；未解决的放 unresolved_action_ids，不能重叠。"
            "无法安全修补才返回 status=no_change。"
        ) + UNIT_TEST_STRUCTURED_CONTENT_CONTRACT},
        {"role": "user", "content": (
            f"章节：{chapter_title}\n\n复核动作：\n{json.dumps(actions, ensure_ascii=False)}\n\n"
            f"数量与写作合同：\n{json.dumps(quantity_contract, ensure_ascii=False)}\n\n"
            f"当前全部题目（未修改题由程序保留）：\n{json.dumps(questions, ensure_ascii=False)}\n\n"
            f"本章正文参考：\n{related_markdown_context}\n\n"
            f"历轮拒绝反馈：\n{previous_rejection or '无'}"
        )},
    ]
    return trace_prompt_build(
        "unit_test_question_patch", inputs={"chapter_title": chapter_title,
        "question_count": len(questions), "action_count": len(actions)}, output=messages,
    )
