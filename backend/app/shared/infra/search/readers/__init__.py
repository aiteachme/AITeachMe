from .base import BaseReader, get_registered_reader_names, get_registered_reader_types, register_reader_type
from .bs4_reader import BS4Reader
from .docx_reader import DOCXReader
from .jina_reader import JinaReader
from .pdf_reader import PDFReader
from .pptx_reader import PPTXReader
from .text_reader import TextReader

__all__ = [
    "BaseReader",
    "BS4Reader",
    "DOCXReader",
    "JinaReader",
    "PDFReader",
    "PPTXReader",
    "TextReader",
    "get_registered_reader_names",
    "get_registered_reader_types",
    "register_reader_type",
]
