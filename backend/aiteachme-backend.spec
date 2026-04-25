# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


os.environ.setdefault("AITEACHME_ENABLE_BUILTIN_PDF", "false")

_EXCLUDED_HIDDENIMPORT_PREFIXES = (
    "app.workflows.ingest.common.parsing.pdf",
)

_EXCLUDED_MODULES = [
    "app.workflows.ingest.common.parsing.pdf",
    "app.workflows.ingest.common.parsing.pdf_page_fallback",
    "app.workflows.ingest.common.parsing.pdf_pdfplumber",
    "fitz",
    "pymupdf",
    "pymupdf4llm",
    "pdfminer",
    "pdfplumber",
    "pypdfium2",
    "pypdfium2_raw",
    "pypdf",
    "PyPDF2",
]


def _collect_app_submodules() -> list[str]:
    return [
        module_name
        for module_name in collect_submodules("app")
        if not module_name.startswith(_EXCLUDED_HIDDENIMPORT_PREFIXES)
    ]


datas = [
    ("alembic.ini", "."),
    ("migrations", "migrations"),
]

for package_name in (
    "alembic",
    "fastapi",
    "langgraph",
    "llama_index",
    "markitdown",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "sqlmodel",
    "uvicorn",
):
    datas += collect_data_files(package_name)

datas += collect_data_files(
    "litellm",
    includes=[
        "anthropic_beta_headers_config.json",
        "cost.json",
        "model_prices_and_context_window_backup.json",
        "policy_templates_backup.json",
        "provider_endpoints_support_backup.json",
    ],
)
datas += collect_data_files("litellm.containers", includes=["endpoints.json"])
datas += collect_data_files("litellm.litellm_core_utils.tokenizers")

hiddenimports = []
for package_name in (
    "app",
    "migrations",
    "litellm.litellm_core_utils.tokenizers",
    "uvicorn",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
):
    if package_name == "app":
        hiddenimports += _collect_app_submodules()
    else:
        hiddenimports += collect_submodules(package_name)


a = Analysis(
    ["desktop_server.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aiteachme-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="aiteachme-backend",
)
