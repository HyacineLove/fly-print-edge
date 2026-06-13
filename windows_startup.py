from __future__ import annotations

import platform
import sys
from pathlib import Path

APP_RUN_VALUE_NAME = "FlyPrint Edge"
RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LAUNCHER_EXE_NAME = "flyprint-launcher.exe"


def build_startup_command(launcher_path: Path) -> str:
    return f'"{Path(launcher_path)}"'


def get_default_launcher_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name(LAUNCHER_EXE_NAME)
    return Path(__file__).resolve().with_name(LAUNCHER_EXE_NAME)


def get_windows_startup_enabled(launcher_path: Path | None = None) -> bool:
    if platform.system() != "Windows":
        return False
    import winreg

    target = build_startup_command(launcher_path or get_default_launcher_path())
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_SUBKEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_RUN_VALUE_NAME)
            return str(value).strip() == target
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_windows_startup_enabled(enabled: bool, launcher_path: Path | None = None) -> None:
    if platform.system() != "Windows":
        return
    import winreg

    target = build_startup_command(launcher_path or get_default_launcher_path())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_SUBKEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_RUN_VALUE_NAME, 0, winreg.REG_SZ, target)
            return
        try:
            winreg.DeleteValue(key, APP_RUN_VALUE_NAME)
        except FileNotFoundError:
            return
