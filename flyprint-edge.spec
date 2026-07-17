# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for FlyPrint Edge.

Outputs a single onedir bundle containing:
  - flyprint-edge.exe      (background FastAPI service)
  - flyprint-launcher.exe  (GUI launcher + tray shell)
"""

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()

required_modules = [
    "pystray",
]
missing_required_modules = [name for name in required_modules if importlib.util.find_spec(name) is None]
if missing_required_modules:
    raise SystemExit(
        "Missing required build dependencies: "
        + ", ".join(missing_required_modules)
        + ". Install them into the build venv before running PyInstaller."
    )

hidden_imports = [
    "zeroconf",
    "fitz",
    "PIL._imaging",
    "PIL._webp",
    "pystray",
    "pystray._win32",
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
    "websockets",
    "websockets.legacy",
    "websockets.legacy.client",
    "websockets.legacy.server",
    "qrcode",
    "qrcode.image",
    "qrcode.image.pil",
    "psutil",
]

service_binaries = []

static_src = PROJECT_ROOT / "static"
datas = []
if static_src.is_dir():
    for file_path in sorted(static_src.rglob("*")):
        if file_path.is_file():
            rel = file_path.relative_to(PROJECT_ROOT)
            datas.append((str(file_path), str(rel.parent)))

config_example = PROJECT_ROOT / "config.example.json"
if config_example.is_file():
    datas.append((str(config_example), "."))

for document_name in ("ipp-printing-architecture.md", "ipp-printing-operations.md"):
    document_path = PROJECT_ROOT / "docs" / document_name
    if document_path.is_file():
        datas.append((str(document_path), "docs"))

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

service_analysis = Analysis(
    [str(PROJECT_ROOT / "service_main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=service_binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

launcher_analysis = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

service_pyz = PYZ(service_analysis.pure)
launcher_pyz = PYZ(launcher_analysis.pure)

service_exe = EXE(
    service_pyz,
    service_analysis.scripts,
    [],
    exclude_binaries=True,
    name="flyprint-edge",
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
    icon=None,
)

launcher_exe = EXE(
    launcher_pyz,
    launcher_analysis.scripts,
    [],
    exclude_binaries=True,
    name="flyprint-launcher",
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
    icon=None,
)

coll = COLLECT(
    service_exe,
    launcher_exe,
    service_analysis.binaries,
    launcher_analysis.binaries,
    service_analysis.datas,
    launcher_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="flyprint-edge",
)
