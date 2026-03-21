"""图片解析器：LLM 视觉识别 + 原图保存。"""

from __future__ import annotations

import base64
from pathlib import Path

import structlog

from app.agents.ingest.parse_utils import MIME_MAP, save_image_bytes
from app.agents.ingest.prompts import SYSTEM_PROMPT_IMAGE_PARSE
from app.core.exceptions import FileParseError
from app.core.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, USER

logger = structlog.get_logger()


async def parse_image(file_path: str | Path, asset_dir: Path) -> str:
    """把图片解析为 Markdown，同时保存原图到 asset_dir。"""
    from app.core.llm import acompletion

    path = Path(file_path)
    logger.info("parse_image_start", filename=path.name)

    # 保存原图到 asset_dir
    img_bytes = path.read_bytes()
    original_filename = save_image_bytes(
        img_bytes, asset_dir,
        name_hint=f"original_{path.stem}",
        ext=path.suffix,
    )

    mime_type = MIME_MAP.get(path.suffix.lower(), "image/png")
    encoded = base64.b64encode(img_bytes).decode("utf-8")
    prompt = populate_prompt(SYSTEM_PROMPT_IMAGE_PARSE)
    messages: list[ChatMessage] = [
        {
            "role": USER,
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        }
    ]

    try:
        text = await acompletion(messages)
    except Exception as exc:
        logger.error("parse_image_failed", filename=path.name, error=str(exc))
        raise FileParseError(path.name, reason=f"图片解析失败：{exc}") from exc

    if not text.strip():
        raise FileParseError(path.name, reason="图片解析结果为空。")

    # 在 markdown 末尾附上原图引用
    text = text.strip()
    text += f"\n\n![原始图片]({original_filename})\n"
    return text
