"""Attach selected original images to the existing Writer teaching prompt."""

from __future__ import annotations

from app.schemas.llm import ChatMessage
from app.workflows.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen_multimodal.lib.models import WriterRereadImage


def add_writer_reread_images(
    messages: list[ChatMessage],
    images: list[WriterRereadImage],
) -> list[ChatMessage]:
    if not images:
        return messages
    content: list[dict] = [{"type": "text", "text": str(messages[-1]["content"])}]
    content.append({"type": "text", "text": (
        "以下是本章需要直接复读的少量原图，其文字摘要已在研究材料中。请结合原图直接完成同一章正文，"
        "核对资料独有的公式、数据、箭头或标注；无需另行输出图片分析、描述或证据 JSON。"
        "原图直接可见的细节可以补充文字摘要；看不清或与正文/摘要冲突的内容须保守说明，不得凭常识猜测。"
        "图片 ID 和来源仅供内部对照，不在学生正文中输出。"
    )})
    for item in images:
        url = f"local://file/{item.file_id}/section/{item.section_ref}/image/{item.image_id}"
        content.extend([
            {"type": "text", "text": (
                f"[IMAGE_BEGIN image_id={item.image_id}]\n"
                f"来源：{url}\n原图文件：{item.asset_filename}\n"
                f"已有摘要：{item.summary}\n复读原因：{item.reread_reason}"
            )},
            {"type": "image_url", "image_url": {"url": item.data_url, "detail": "high"}},
            {"type": "text", "text": f"[IMAGE_END image_id={item.image_id}]"},
        ])
    enriched = [*messages[:-1], {"role": "user", "content": content}]
    return trace_prompt_build(
        "docgen_multimodal_writer",
        inputs={"image_ids": [item.image_id for item in images], "image_count": len(images)},
        output=enriched,
    )


__all__ = ["add_writer_reread_images"]
