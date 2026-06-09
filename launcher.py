from __future__ import annotations

import ctypes
import json
import platform
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import psutil
import pystray
import requests
from PIL import Image, ImageDraw

from windows_startup import build_startup_command

APP_NAME = "FlyPrint Edge"
ACTION_OPEN_USER = "open-user"
ACTION_OPEN_ADMIN = "open-admin"
ACTION_RESTART_SERVICE = "restart-service"
ACTION_EXIT = "exit"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 18761
SERVICE_READY_TIMEOUT_SEC = 20
SERVICE_POLL_INTERVAL_SEC = 0.5
SINGLE_INSTANCE_MUTEX = r"Global\FlyPrintEdgeLauncher"


def normalize_launcher_action(raw: str | None) -> str:
    if raw in (None, "", "--open-user"):
        return ACTION_OPEN_USER
    if raw == "--open-admin":
        return ACTION_OPEN_ADMIN
    if raw == "--restart-service":
        return ACTION_RESTART_SERVICE
    if raw == "--exit":
        return ACTION_EXIT
    return ACTION_OPEN_USER


def build_edge_command(edge_exe: str, url: str, mode: str, profile_dir: Path) -> list[str]:
    command = [
        edge_exe,
        "--no-first-run",
        "--disable-features=msUndersideButton",
        f"--user-data-dir={profile_dir}",
    ]
    if mode == "admin":
        command.extend(["--new-window", url])
    else:
        command.extend(["--kiosk", url, "--edge-kiosk-type=fullscreen"])
    return command


def resolve_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_runtime_config(install_dir: Path) -> dict:
    config_path = install_dir / "config.json"
    if not config_path.is_file():
        return {"network": {"bind_address": "127.0.0.1", "port": 7860}}
    try:
        return json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"network": {"bind_address": "127.0.0.1", "port": 7860}}


def resolve_local_base_url(config: dict) -> str:
    network = config.get("network", {})
    host = str(network.get("bind_address") or "127.0.0.1").strip()
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = int(network.get("port") or 7860)
    return f"http://{host}:{port}"


def resolve_edge_executable() -> str:
    if platform.system() != "Windows":
        raise RuntimeError("FlyPrint launcher currently supports Windows only")

    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            candidates.insert(0, Path(value))
    except OSError:
        pass

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Microsoft Edge executable not found")


def is_service_ready(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/api/status", timeout=1.5)
        payload = response.json()
        return response.ok and payload.get("status") == "online"
    except Exception:
        return False


def show_launcher_error(message: str) -> None:
    if platform.system() != "Windows":
        return
    ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)


def open_url_in_edge(mode: str, base_url: str, install_dir: Path) -> None:
    edge_exe = resolve_edge_executable()
    profile_name = "admin-browser-profile" if mode == "admin" else "user-browser-profile"
    profile_dir = install_dir / "runtime" / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    url = f"{base_url}/admin" if mode == "admin" else base_url
    command = build_edge_command(edge_exe=edge_exe, url=url, mode=mode, profile_dir=profile_dir)
    subprocess.Popen(command, cwd=str(install_dir))


def open_logs_dir(install_dir: Path) -> None:
    logs_dir = install_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(logs_dir)])


def open_install_dir(install_dir: Path) -> None:
    subprocess.Popen(["explorer.exe", str(install_dir)])


class SingleInstance:
    def __init__(self, name: str):
        self._handle = None
        self._already_running = False
        self._name = name

    def acquire(self) -> bool:
        if platform.system() != "Windows":
            return True

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            return False
        self._handle = handle
        self._already_running = ctypes.windll.kernel32.GetLastError() == 183
        return not self._already_running

    def release(self) -> None:
        if self._handle and platform.system() == "Windows":
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


class _CommandHandler(socketserver.BaseRequestHandler):
    def handle(self):
        action = self.request.recv(1024).decode("utf-8").strip() or ACTION_OPEN_USER
        self.server.command_callback(action)  # type: ignore[attr-defined]
        self.request.sendall(b"ok")


class CommandServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, command_callback: Callable[[str], None]):
        super().__init__((CONTROL_HOST, CONTROL_PORT), _CommandHandler)
        self.command_callback = command_callback


def send_control_command(action: str) -> bool:
    for _ in range(5):
        try:
            with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=1.5) as conn:
                conn.sendall(action.encode("utf-8"))
                conn.recv(32)
                return True
        except OSError:
            time.sleep(0.3)
    return False


class LauncherApp:
    def __init__(self):
        self.install_dir = resolve_install_dir()
        self.config = resolve_runtime_config(self.install_dir)
        self.base_url = resolve_local_base_url(self.config)
        self.service_exe = self.install_dir / "flyprint-edge.exe"
        self.command_server: CommandServer | None = None
        self.command_thread: threading.Thread | None = None
        self.tray_icon = None

    def _service_creation_flags(self) -> int:
        flags = 0
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return flags

    def _start_service_process(self) -> None:
        if not self.service_exe.is_file():
            raise RuntimeError(f"Missing service executable: {self.service_exe}")
        subprocess.Popen(
            [str(self.service_exe)],
            cwd=str(self.install_dir),
            creationflags=self._service_creation_flags(),
        )

    def _terminate_service_processes(self) -> None:
        service_path = str(self.service_exe.resolve()).lower()
        matched_processes: list[psutil.Process] = []

        for process in psutil.process_iter(["pid", "exe", "cmdline"]):
            try:
                exe_path = (process.info.get("exe") or "").lower()
                cmdline = [str(item).lower() for item in (process.info.get("cmdline") or [])]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if exe_path == service_path or service_path in cmdline:
                matched_processes.append(process)

        for process in matched_processes:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not matched_processes:
            return

        _, alive = psutil.wait_procs(matched_processes, timeout=5)
        for process in alive:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def ensure_service_ready(self, restart: bool = False) -> None:
        if restart:
            self._terminate_service_processes()

        if not restart and is_service_ready(self.base_url):
            return

        self._start_service_process()
        deadline = time.monotonic() + SERVICE_READY_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if is_service_ready(self.base_url):
                return
            time.sleep(SERVICE_POLL_INTERVAL_SEC)
        raise RuntimeError("FlyPrint service did not become ready in time")

    def restart_service(self) -> None:
        self.ensure_service_ready(restart=True)

    def _run_action(self, action: str) -> None:
        if action == ACTION_OPEN_ADMIN:
            self.ensure_service_ready()
            open_url_in_edge("admin", self.base_url, self.install_dir)
            return
        if action == ACTION_RESTART_SERVICE:
            self.restart_service()
            return
        if action == ACTION_EXIT:
            self.shutdown()
            return
        self.ensure_service_ready()
        open_url_in_edge("user", self.base_url, self.install_dir)

    def dispatch(self, action: str) -> None:
        try:
            self._run_action(action)
        except Exception as exc:
            show_launcher_error(str(exc))

    def start_command_server(self) -> None:
        self.command_server = CommandServer(self.dispatch)
        self.command_thread = threading.Thread(target=self.command_server.serve_forever, daemon=True)
        self.command_thread.start()

    def shutdown(self) -> None:
        if self.command_server:
            self.command_server.shutdown()
            self.command_server.server_close()
            self.command_server = None
        if self.tray_icon is not None:
            self.tray_icon.stop()

    def create_tray_icon(self):
        image = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(37, 99, 235, 255))
        draw.rectangle((18, 18, 46, 46), fill=(255, 255, 255, 255))

        return pystray.Icon(
            "flyprint-edge",
            image,
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("打开用户页", lambda _icon, _item: self.dispatch(ACTION_OPEN_USER)),
                pystray.MenuItem("打开管理页", lambda _icon, _item: self.dispatch(ACTION_OPEN_ADMIN)),
                pystray.MenuItem("重启服务", lambda _icon, _item: self.dispatch(ACTION_RESTART_SERVICE)),
                pystray.MenuItem("打开日志目录", lambda _icon, _item: open_logs_dir(self.install_dir)),
                pystray.MenuItem("打开安装目录", lambda _icon, _item: open_install_dir(self.install_dir)),
                pystray.MenuItem("退出", lambda _icon, _item: self.dispatch(ACTION_EXIT)),
            ),
        )

    def run(self, initial_action: str) -> int:
        self.start_command_server()
        self.tray_icon = self.create_tray_icon()
        threading.Thread(target=lambda: self.dispatch(initial_action), daemon=True).start()
        self.tray_icon.run()
        return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    action = normalize_launcher_action(argv[0] if argv else None)
    instance = SingleInstance(SINGLE_INSTANCE_MUTEX)
    if not instance.acquire():
        send_control_command(action)
        return 0
    try:
        return LauncherApp().run(action)
    finally:
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
