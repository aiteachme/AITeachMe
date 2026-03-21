"""文件解析器集合（按格式拆分到独立模块，此处统一 re-export）。

每个 parser 签名统一为：
    async def parse_xxx(file_path: str | Path, asset_dir: Path) -> str
返回 markdown 文本，其中不可文本化的图片已提取到 asset_dir 并以相对路径引用。
"""

from app.agents.ingest.parse_docx import parse_docx as parse_docx
from app.agents.ingest.parse_image import parse_image as parse_image
from app.agents.ingest.parse_pdf import parse_pdf as parse_pdf
from app.agents.ingest.parse_pptx import parse_pptx as parse_pptx

__all__ = ["parse_pdf", "parse_pptx", "parse_docx", "parse_image"]
