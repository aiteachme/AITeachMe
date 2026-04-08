"""Build Planner 的中文提示词。"""

from __future__ import annotations

import json

from app.workflows.digest.shared.models import SharedInputs


def _mode_contract(digest_mode: str) -> str:
    normalized_mode = (digest_mode or "systematic").strip().lower()
    if normalized_mode == "sprint":
        return """
模式硬约束（必须全部满足）：
1. `digest_mode` 固定为 `sprint`。
2. `chapter_plan` 必须且只能有 4 章，顺序固定为：
   - 第 1 章：概念破冰
   - 第 2 章：公式武器库
   - 第 3 章：真题实战
   - 第 4 章：防坑指南
3. 不允许新增、删减、改名或调换这 4 章。
4. 每章的 `writing_instructions` 必须具体到写作动作，不能只写“详细说明”“展开讲解”这类空话。
5. 方案摘要必须体现“冲刺、抓分、速记、易错点、题型拆解”的目标。
6. 自然语言内容必须全部使用中文。
""".strip()
    return """
模式硬约束（必须全部满足）：
1. `digest_mode` 固定为 `systematic`。
2. `chapter_plan` 章节数必须在 6 到 10 章之间。
3. 第 1 章标题必须是“全景导论”。
4. 最后一章标题必须是“总结与延展”。
5. 中间章节必须围绕主题逐层展开，不允许退化成原始文件目录复写。
6. 中间章节的 `writing_instructions` 必须稳定体现：
   “前置知识 -> 动机引入 -> 核心定义与定理 -> 推理与应用 -> 本章要点”。
7. 方案摘要必须体现“系统化、可反复精读、重视定义/推导/应用”的目标。
8. 自然语言内容必须全部使用中文。
""".strip()


def build_planner_prompt(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    shared_inputs: SharedInputs,
    message_history: list[str],
    latest_plan: dict | None,
) -> str:
    source_summary = [
        {
            "file_id": packet.file_id,
            "filename": packet.filename,
            "char_count": packet.char_count,
            "has_formulas": packet.has_formulas,
            "has_tables": packet.has_tables,
            "has_images": packet.has_images,
        }
        for packet in shared_inputs.source_packets[:12]
    ]
    topic_hints = [title for title in shared_inputs.fast_hints.chapter_candidates[:12] if title]
    prior_plan = json.dumps(latest_plan, ensure_ascii=False, indent=2) if latest_plan else "null"
    conversation = "\n".join(f"- {item}" for item in message_history if item.strip()) or "- 暂无额外修改意见"

    return f"""
你是 AITeachMe 的 Build Planner。
你的任务不是闲聊，而是产出一份“用户可以直接确认并开始构建”的正式知识文档方案。

你必须只返回一个合法 JSON 对象，不要输出任何解释、前后缀、注释或 Markdown 代码块。

学科：{subject}
用户目标：{user_goal}
期望文档模式：{digest_mode}
期望表达风格：{tone}

学科画像：
{shared_inputs.subject_profile.build_context_string()}

快速主题提示：
{json.dumps(topic_hints, ensure_ascii=False)}

资料摘要：
{json.dumps(source_summary, ensure_ascii=False, indent=2)}

上一版方案：
{prior_plan}

规划对话历史：
{conversation}

输出总要求：
1. JSON 的字段名保持英文 schema，不要发明新字段。
2. 所有自然语言字段内容必须使用中文，包括 `title`、`objective`、`writing_instructions`、`plan_summary`。
3. `chapter_plan` 中每一章都必须有：
   - `chapter_index`
   - `title`
   - `objective`
   - `required_elements`
   - `search_queries`
   - `writing_instructions`
   - `media_hints`
4. `research_queries` 必须去重，并能覆盖整份文档的研究范围。
5. `media_plan` 必须明确说明 Mermaid、图片、交互式 HTML 的开关。
6. `build_constraints` 必须体现质量约束，如目标字数、是否包含来源、是否包含练习、章节数限制等。
7. 章节结构必须优先服从学习路径，而不是原始文件目录。
8. 如果对话历史里有修改意见，必须吸收进当前方案，而不是忽略。
9. 不允许出现英文标题、英文摘要、英文章节目标。

{_mode_contract(digest_mode)}
""".strip()


__all__ = ["build_planner_prompt"]
