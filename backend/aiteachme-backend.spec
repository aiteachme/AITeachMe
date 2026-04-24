# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


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
    "pymupdf",
    "pymupdf4llm",
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
    excludes=[],
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
