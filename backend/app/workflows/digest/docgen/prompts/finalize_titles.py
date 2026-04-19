"""Prompt builders used by DocGen planning/finalization helpers."""

from app.workflows.digest.docgen.prompts.common import (
    build_docgen_gap_query_messages,
    build_docgen_sub_query_messages,
)


def build_finalize_chapter_titles_messages(*, digest_mode: str, chapters: list[dict]) -> list[dict[str, str]]:
    """Build messages for final chapter title review."""

    return [
        {
            "role": "system",
            "content": (
                "你是 AITeachMe 的中文课程标题编辑。"
                "你只负责复核并优化章节标题，不改变章节顺序、章节数量和用户确认过的语义边界。"
                "标题要自然、具体、像真实讲义目录，避免“核心模块”“复盘安排”“章节一”这类呆板泛化标题。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"文档模式：{digest_mode}\n\n"
                "请根据每章的 confirmed_title、current_title、summary、headings 和 excerpt 生成最终标题。\n"
                "要求：\n"
                "1. 必须保持 chapter_index 不变。\n"
                "2. 不新增、不删除、不重排章节。\n"
                "3. 标题用中文，简洁但具体，通常 6-18 个汉字。\n"
                "4. 不要机械沿用初始标题；如果初始标题合适，也可以微调后保留。\n"
                "5. 标题之间不能重复，最好能串成一条学习路径。\n\n"
                f"章节材料：\n{chapters}"
            ),
        },
    ]


__all__ = [
    "build_finalize_chapter_titles_messages",
    "build_docgen_gap_query_messages",
    "build_docgen_sub_query_messages",
]
