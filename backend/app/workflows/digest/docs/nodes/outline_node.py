"""阶段二：全局目录树构建节点。

Map 阶段提取各文本块局部标题，Reduce 阶段全局统筹为目录树。
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from app.core.database import managed_session
from app.core.llm import acompletion, acompletion_structured
from app.core.model_router import TaskType
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.prompts.docgen_prompts import (
    GLOBAL_OUTLINE_PROMPT,
    LOCAL_OUTLINE_PROMPT,
)

logger = structlog.get_logger()


def _extract_existing_headers(content: str) -> list[str]:
    """从 Markdown 内容中提取已有的 H1/H2/H3 标题。"""

    headers: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            # 提取标题文本（去掉 # 和空格）
            title = stripped.lstrip("#").strip()
            if title:
                headers.append(title)
    return headers


async def _generate_local_titles(content: str) -> list[str]:
    """使用 LLM 为无标题文本生成局部子标题。"""

    # 截取前 3000 字作为输入避免超长
    truncated = content[:3000]
    prompt = LOCAL_OUTLINE_PROMPT.format(text=truncated)

    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        # 解析 JSON 数组
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        titles = json.loads(cleaned)
        if isinstance(titles, list):
            return [str(t) for t in titles[:5]]
    except Exception as exc:
        logger.warning("outline_local_titles_failed", error=str(exc))

    return ["未分类内容"]


def build_outline_node(*, context: WorkflowContext):
    """构建全局目录树节点。"""

    async def outline_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="outline")
        node_logger.info("outline_started")

        subject = state["subject"]
        job_id = state["job_id"]
        clean_chunks = state.get("clean_chunks", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="outlining", progress=25,
            )

        # 1) Map 阶段：提取/生成各块的局部标题
        all_local_outlines: list[dict] = []

        for i, chunk in enumerate(clean_chunks):
            content = chunk["content"]
            existing_headers = _extract_existing_headers(content)

            if len(existing_headers) >= 2:
                # 已有足够标题，直接使用
                local_titles = existing_headers[:10]
            else:
                # 无/少标题，用 LLM 生成
                local_titles = await _generate_local_titles(content)

            all_local_outlines.append({
                "chunk_index": i,
                "source_filename": chunk.get("source_filename", f"chunk_{i}"),
                "titles": local_titles,
            })
            node_logger.info(
                "outline_map_done",
                chunk_index=i,
                title_count=len(local_titles),
            )

        # 2) Reduce 阶段：全局统筹
        local_outlines_text = "\n".join(
            f"文本块 {item['chunk_index']}（来源：{item['source_filename']}）：{', '.join(item['titles'])}"
            for item in all_local_outlines
        )

        global_prompt = GLOBAL_OUTLINE_PROMPT.format(
            chunk_count=len(clean_chunks),
            local_outlines=local_outlines_text,
        )

        try:
            result = await acompletion(
                [{"role": "user", "content": global_prompt}],
                task_type=TaskType.DOCGEN,
            )
            cleaned_result = result.strip()
            if cleaned_result.startswith("```"):
                cleaned_result = cleaned_result.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            outline_tree = json.loads(cleaned_result)
        except Exception as exc:
            node_logger.error("outline_global_failed", error=str(exc))
            # 兜底：如果 LLM 失败，创建简单的一对一映射
            outline_tree = {
                "chapters": [
                    {
                        "chapter_index": i + 1,
                        "title": chunk.get("source_filename", f"第{i + 1}章"),
                        "sections": [
                            {
                                "title": "全部内容",
                                "source_chunk_indices": [i],
                            }
                        ],
                    }
                    for i, chunk in enumerate(clean_chunks)
                ]
            }

        # 3) 组装 chapter_assignments：每章分配的 clean_chunks 内容
        chapters = outline_tree.get("chapters", [])
        chapter_assignments: list[dict] = []

        for chapter in chapters:
            ch_index = chapter.get("chapter_index", 0)
            ch_title = chapter.get("title", f"第{ch_index}章")
            sections = chapter.get("sections", [])

            # 收集本章引用的所有原始文本块
            source_indices: set[int] = set()
            for section in sections:
                for idx in section.get("source_chunk_indices", []):
                    if 0 <= idx < len(clean_chunks):
                        source_indices.add(idx)

            source_contents = [
                clean_chunks[idx]["content"]
                for idx in sorted(source_indices)
            ]

            chapter_assignments.append({
                "chapter_index": ch_index,
                "title": ch_title,
                "sections": sections,
                "source_contents": source_contents,
                "source_file_ids": [
                    clean_chunks[idx].get("file_id", 0)
                    for idx in sorted(source_indices)
                ],
            })

        # 4) 保存中间产物
        intermediate_dir = build_docgen_intermediate_dir(subject)
        intermediate_dir.mkdir(parents=True, exist_ok=True)

        outline_path = intermediate_dir / "outline_tree.json"
        outline_path.write_text(
            json.dumps(outline_tree, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        assignments_path = intermediate_dir / "chapter_assignments.json"
        assignments_summary = [
            {
                "chapter_index": a["chapter_index"],
                "title": a["title"],
                "section_count": len(a["sections"]),
                "source_char_count": sum(len(c) for c in a["source_contents"]),
            }
            for a in chapter_assignments
        ]
        assignments_path.write_text(
            json.dumps(assignments_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id,
                progress=40,
                total_chapters=len(chapter_assignments),
            )

        node_logger.info(
            "outline_completed",
            chapter_count=len(chapter_assignments),
        )
        return {
            "outline_tree": outline_tree,
            "chapter_assignments": chapter_assignments,
        }

    return outline_node
