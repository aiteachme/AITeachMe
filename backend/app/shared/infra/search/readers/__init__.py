from .base import BaseReader, BaseScraper, get_registered_reader_names, get_registered_reader_types, register_reader_type
from .bs4_scraper import BS4Scraper
from .docx_scraper import DOCXScraper
from .pdf_scraper import PDFScraper
from .pptx_scraper import PPTXScraper
from .text_scraper import TextScraper

__all__ = [
    "BaseReader",
    "BaseScraper",
    "BS4Scraper",
    "DOCXScraper",
    "PDFScraper",
    "PPTXScraper",
    "TextScraper",
    "get_registered_reader_names",
    "get_registered_reader_types",
    "register_reader_type",
]


