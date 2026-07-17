"""Single LibreOffice conversion path used by preview and printing."""

from __future__ import annotations

import os
import subprocess
import sys
import ctypes
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple


_REMOVED_ENV_KEYS = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYI_TEMP_DIR",
    "PYINSTALLER_RESET_ENVIRONMENT",
    "_MEIPASS2",
    "UNO_PATH",
    "URE_BOOTSTRAP",
)

_CONVERSION_LOCK = threading.Lock()


@contextmanager
def clean_external_dll_search_path(logger=None):
    """Prevent a frozen app's bundled DLL directory leaking into native children."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if sys.platform != "win32" or not getattr(sys, "frozen", False) or not bundle_dir:
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_dll_directory = kernel32.SetDllDirectoryW
    set_dll_directory.argtypes = [ctypes.c_wchar_p]
    set_dll_directory.restype = ctypes.c_bool
    if not set_dll_directory(None):
        raise OSError(ctypes.get_last_error(), "SetDllDirectoryW(None) failed")
    if logger:
        logger.info(
            "LibreOffice DLL search isolation enabled: removed_bundle_dir=%s",
            bundle_dir,
        )
    try:
        yield
    finally:
        if not set_dll_directory(str(bundle_dir)):
            raise OSError(
                ctypes.get_last_error(),
                f"restoring PyInstaller DLL directory failed: {bundle_dir}",
            )
        if logger:
            logger.info(
                "LibreOffice DLL search isolation restored: bundle_dir=%s",
                bundle_dir,
            )


def build_libreoffice_environment(soffice_dir: str):
    """Return the normal Windows environment with Python/UNO leakage removed."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    system32 = os.path.join(system_root, "System32")
    env = os.environ.copy()
    removed_keys = []
    for key in _REMOVED_ENV_KEYS:
        if key in env:
            removed_keys.append(key)
            env.pop(key, None)
    env["PATH"] = os.pathsep.join([soffice_dir, system32, system_root])
    return env, removed_keys


def convert_document_to_pdf(
    soffice: str,
    source_path: str,
    output_dir: str,
    profile_dir: str,
    logger=None,
    timeout: int = 60,
) -> Tuple[Optional[str], Optional[str]]:
    """Convert one document through the single persistent FlyPrint profile."""
    source_path = os.path.abspath(source_path)
    output_dir = os.path.abspath(output_dir)
    profile_dir = os.path.abspath(profile_dir)
    output_path = os.path.join(
        output_dir,
        f"{os.path.splitext(os.path.basename(source_path))[0]}.pdf",
    )
    if not os.path.isfile(source_path):
        return None, f"source document does not exist: {source_path}"
    if not os.path.isfile(soffice):
        return None, f"LibreOffice executable does not exist: {soffice}"

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(profile_dir, exist_ok=True)

    soffice_dir = os.path.dirname(os.path.abspath(soffice))
    profile_url = Path(profile_dir).as_uri()
    command = [
        soffice,
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile_url}",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        output_dir,
        source_path,
    ]
    env, removed_keys = build_libreoffice_environment(soffice_dir)
    lock_started_at = time.perf_counter()
    with _CONVERSION_LOCK:
        lock_wait_ms = (time.perf_counter() - lock_started_at) * 1000
        if os.path.exists(output_path):
            os.remove(output_path)
        started_at = time.perf_counter()
        if logger:
            logger.info(
                "LibreOffice conversion command: executable=%s cwd=%s output_dir=%s profile=%s lock_wait_ms=%.1f command=%r",
                soffice,
                soffice_dir,
                output_dir,
                profile_dir,
                lock_wait_ms,
                command,
            )
            logger.info(
                "LibreOffice child environment: path=%s removed_keys=%s",
                env.get("PATH"),
                removed_keys,
            )
        try:
            with clean_external_dll_search_path(logger=logger):
                result = subprocess.run(
                    command,
                    cwd=soffice_dir,
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=timeout,
                )
            output_exists = os.path.isfile(output_path)
            output_size = os.path.getsize(output_path) if output_exists else 0
            returncode_hex = (
                f"0x{result.returncode & 0xFFFFFFFF:08X}"
                if isinstance(result.returncode, int)
                else None
            )
            if logger:
                logger.info(
                    "LibreOffice finished: returncode=%s (%s) elapsed_ms=%.1f output_exists=%s output_size=%s stdout=%r stderr=%r",
                    result.returncode,
                    returncode_hex,
                    (time.perf_counter() - started_at) * 1000,
                    output_exists,
                    output_size,
                    result.stdout,
                    result.stderr,
                )
            if result.returncode == 0 and output_exists and output_size > 0:
                return output_path, None
            return None, (
                f"LibreOffice failed (returncode={result.returncode}, "
                f"stdout={result.stdout.strip()!r}, stderr={result.stderr.strip()!r}, "
                f"output_exists={output_exists}, output_size={output_size})"
            )
        except Exception as exc:
            if logger:
                logger.exception("LibreOffice conversion raised an exception")
            return None, str(exc)
