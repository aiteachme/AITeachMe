# -*- mode: python ; coding: utf-8 -*-

import os

from pyinstaller_desktop_common import (
    EXCLUDED_MODULE_PREFIXES,
    collect_app_hiddenimports,
    collect_runtime_datas,
    collect_runtime_hiddenimports,
    filter_toc_entries,
)


os.environ.setdefault("AITEACHME_ENABLE_BUILTIN_PDF", "false")

datas = collect_runtime_datas()
hiddenimports = collect_app_hiddenimports() + ["migrations"] + collect_runtime_hiddenimports()


a = Analysis(
    ["desktop_server.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(EXCLUDED_MODULE_PREFIXES),
    noarchive=False,
    optimize=0,
)
a.pure = filter_toc_entries(a.pure)
a.binaries = filter_toc_entries(a.binaries)
a.datas = filter_toc_entries(a.datas)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aiteachme-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=".",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="../docs/brand/app-icon.ico",
)
