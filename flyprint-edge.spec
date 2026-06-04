# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for FlyPrint Edge Kiosk (onedir build).

Build:
    pyinstaller flyprint-edge.spec --clean --noconfirm
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()

# Hidden imports for packages with dynamic imports / C extensions
hidden_imports = [
    # pywin32 COM modules
    "win32print",
    "win32api",
    "win32gui",
    "win32timezone",
    "win32com",
    "win32com.client",
    "win32com.server",
    "pythoncom",
    # pymupdf (fitz)
    "fitz",
    # Pillow image plugins
    "PIL._imaging",
    "PIL._webp",
    # FastAPI / Starlette / Uvicorn
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "starlette.middleware",
    "starlette.middleware.cors",
    "pydantic",
    "pydantic.deprecated",
    # websockets
    "websockets",
    "websockets.legacy",
    "websockets.legacy.client",
    "websockets.legacy.server",
    # misc
    "qrcode",
    "qrcode.image",
    "qrcode.image.pil",
    "pandas",
    "psutil",
    "zeroconf",
]

# Collect entire static/ directory as data files
static_src = PROJECT_ROOT / "static"
static_dst = "static"
datas = []
if static_src.is_dir():
    for f in sorted(static_src.rglob("*")):
        if f.is_file():
            rel = f.relative_to(PROJECT_ROOT)
            datas.append((str(f), str(rel.parent)))

# Include config.example.json
config_example = PROJECT_ROOT / "config.example.json"
if config_example.is_file():
    datas.append((str(config_example), "."))

# Exclusions
excludes = [
    "tkinter",
    "test",
    "tests",
    "unittest",
    "setuptools",
    "pip",
    "wheel",
    "pkg_resources",
]

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="flyprint-edge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # True = shows console (for server logging). Set False for silent.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="flyprint-edge",
)
