"""FlyPrint LibreOffice DOCX conversion latency probe.

This diagnostic does not print, change LibreOffice settings, or modify FlyPrint
configuration. Every test uses its own LibreOffice user profile.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback


APP_NAME = "FlyPrint LibreOffice 延时探测器"
DEFAULT_SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
REMOVED_ENV_KEYS = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYI_TEMP_DIR",
    "PYINSTALLER_RESET_ENVIRONMENT",
    "_MEIPASS2",
    "UNO_PATH",
    "URE_BOOTSTRAP",
)


def configure_console() -> None:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_environment(soffice_dir: Path) -> tuple[dict[str, str], list[str]]:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env = os.environ.copy()
    removed = []
    for key in REMOVED_ENV_KEYS:
        if key in env:
            removed.append(key)
            env.pop(key, None)
    env["PATH"] = os.pathsep.join((str(soffice_dir), os.path.join(system_root, "System32"), system_root))
    return env, removed


class DllSearchIsolation:
    def __init__(self):
        self.bundle_dir = getattr(sys, "_MEIPASS", None)
        self.setter = None

    def __enter__(self):
        if sys.platform != "win32" or not getattr(sys, "frozen", False) or not self.bundle_dir:
            return self
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.setter = kernel32.SetDllDirectoryW
        self.setter.argtypes = [ctypes.c_wchar_p]
        self.setter.restype = ctypes.c_bool
        if not self.setter(None):
            raise OSError(ctypes.get_last_error(), "SetDllDirectoryW(None) failed")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.setter and not self.setter(str(self.bundle_dir)):
            raise OSError(ctypes.get_last_error(), "restoring PyInstaller DLL directory failed")


def conversion_command(soffice: Path, profile: Path, output_dir: Path, source: Path) -> list[str]:
    return [
        str(soffice),
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        str(output_dir),
        str(source),
    ]


def wait_for_file(path: Path, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return True
        time.sleep(0.05)
    return path.is_file() and path.stat().st_size > 0


def run_conversion(
    *,
    name: str,
    soffice: Path,
    profile: Path,
    output_dir: Path,
    source: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.stem}.pdf"
    output.unlink(missing_ok=True)
    command = conversion_command(soffice, profile, output_dir, source)
    started = time.perf_counter()
    try:
        with DllSearchIsolation():
            result = subprocess.run(
                command,
                cwd=str(soffice.parent),
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        output_ready = wait_for_file(output, timeout_seconds)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "name": name,
            "success": result.returncode == 0 and output_ready,
            "elapsed_ms": round(elapsed_ms, 1),
            "returncode": result.returncode,
            "output_path": str(output),
            "output_size": output.stat().st_size if output_ready else 0,
            "output_sha256": sha256_file(output) if output_ready else "",
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "command": command,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "success": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": f"conversion timed out after {timeout_seconds}s",
            "stdout": str(exc.stdout or "")[-4000:],
            "stderr": str(exc.stderr or "")[-4000:],
            "command": command,
        }
    except Exception as exc:
        return {
            "name": name,
            "success": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "command": command,
        }


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def listening_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    result = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    expected = f"127.0.0.1:{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1] == expected and parts[3].upper() == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def wait_for_listener(port: int, process: subprocess.Popen, timeout_seconds: int) -> tuple[bool, float, int | None]:
    started = time.perf_counter()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True, (time.perf_counter() - started) * 1000, listening_pid(port)
        except OSError:
            if process.poll() is not None and time.perf_counter() - started > 3:
                return False, (time.perf_counter() - started) * 1000, None
            time.sleep(0.1)
    return False, (time.perf_counter() - started) * 1000, None


def stop_listener(process: subprocess.Popen, listener_pid: int | None) -> None:
    if os.name == "nt":
        for pid in dict.fromkeys((listener_pid, process.pid)):
            if not pid:
                continue
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                capture_output=True,
                check=False,
            )
    elif process.poll() is None:
        process.kill()


def run_persistent_tests(
    *,
    soffice: Path,
    profile: Path,
    output_root: Path,
    source: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict:
    soffice_console = soffice.with_name("soffice.com")
    if not soffice_console.is_file():
        return {
            "supported": False,
            "error": f"persistent mode requires {soffice_console}",
            "results": [],
        }
    profile.mkdir(parents=True, exist_ok=True)
    port = reserve_local_port()
    command = [
        str(soffice_console),
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext",
    ]
    listener_log_path = output_root / "persistent-listener.log"
    listener_log = listener_log_path.open("w", encoding="utf-8", errors="replace")
    process = None
    listener_pid = None
    try:
        with DllSearchIsolation():
            process = subprocess.Popen(
                command,
                cwd=str(soffice.parent),
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=listener_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        ready, startup_ms, listener_pid = wait_for_listener(port, process, min(timeout_seconds, 60))
        if not ready:
            return {
                "supported": True,
                "listener_ready": False,
                "listener_start_ms": round(startup_ms, 1),
                "listener_pid": listener_pid,
                "listener_log": str(listener_log_path),
                "command": command,
                "results": [],
            }
        results = [
            run_conversion(
                name="persistent-first",
                soffice=soffice,
                profile=profile,
                output_dir=output_root / "persistent-first",
                source=source,
                env=env,
                timeout_seconds=timeout_seconds,
            ),
            run_conversion(
                name="persistent-second",
                soffice=soffice,
                profile=profile,
                output_dir=output_root / "persistent-second",
                source=source,
                env=env,
                timeout_seconds=timeout_seconds,
            ),
        ]
        return {
            "supported": True,
            "listener_ready": True,
            "listener_start_ms": round(startup_ms, 1),
            "listener_pid": listener_pid,
            "listener_log": str(listener_log_path),
            "command": command,
            "results": results,
        }
    except Exception as exc:
        return {
            "supported": True,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "command": command,
            "results": [],
        }
    finally:
        if process is not None:
            stop_listener(process, listener_pid)
        listener_log.close()


def prompt_path(label: str, default: Path | None = None) -> Path:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip().strip('"')
    return Path(value) if value else Path(default or "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--soffice", help="完整 soffice.exe 路径")
    parser.add_argument("--document", help="要测试的 DOC/DOCX 文件")
    parser.add_argument("--timeout", type=int, default=120, help="每次转换超时秒数，默认 120")
    return parser.parse_args()


def write_text_report(path: Path, report: dict) -> None:
    lines = [
        APP_NAME,
        f"created_at={report['created_at']}",
        f"system={report['system']}",
        f"soffice={report['soffice']}",
        f"document={report['document_original']}",
        "",
    ]
    for result in report["results"] + report["persistent"].get("results", []):
        lines.extend(
            [
                f"[{result.get('name')}]",
                f"success={result.get('success')}",
                f"elapsed_ms={result.get('elapsed_ms')}",
                f"returncode={result.get('returncode')}",
                f"output_path={result.get('output_path', '')}",
                f"output_size={result.get('output_size', 0)}",
                f"error={result.get('error', '')}",
                f"stdout={result.get('stdout', '')}",
                f"stderr={result.get('stderr', '')}",
                "",
            ]
        )
    persistent = report["persistent"]
    lines.extend(
        [
            "[persistent-listener]",
            f"supported={persistent.get('supported')}",
            f"listener_ready={persistent.get('listener_ready')}",
            f"listener_start_ms={persistent.get('listener_start_ms')}",
            f"listener_pid={persistent.get('listener_pid')}",
            f"listener_log={persistent.get('listener_log', '')}",
            f"error={persistent.get('error', '')}",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    configure_console()
    args = parse_args()
    print(APP_NAME)
    print("不会打印、不会修改 FlyPrint 或 LibreOffice 配置。")
    print("每种模式使用隔离的 LibreOffice Profile。\n")

    soffice = Path(args.soffice) if args.soffice else prompt_path("请输入 soffice.exe 路径", DEFAULT_SOFFICE)
    document = Path(args.document) if args.document else prompt_path("请输入 DOC/DOCX 文件路径")
    soffice = soffice.expanduser().resolve()
    document = document.expanduser().resolve()
    if not soffice.is_file():
        print(f"错误：未找到 LibreOffice：{soffice}")
        return 2
    if not document.is_file() or document.suffix.lower() not in {".doc", ".docx"}:
        print(f"错误：请选择有效的 DOC/DOCX 文件：{document}")
        return 2

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_root = executable_dir() / "logs" / f"libreoffice-latency-{timestamp}"
    outputs = run_root / "outputs"
    profiles = run_root / "profiles"
    outputs.mkdir(parents=True, exist_ok=True)
    profiles.mkdir(parents=True, exist_ok=True)
    source = run_root / f"input{document.suffix.lower()}"
    shutil.copy2(document, source)
    env, removed_keys = clean_environment(soffice.parent)

    print("\n开始测试，请勿在测试期间打开 LibreOffice……")
    isolated = run_conversion(
        name="isolated-new-profile",
        soffice=soffice,
        profile=profiles / "isolated",
        output_dir=outputs / "isolated-new-profile",
        source=source,
        env=env,
        timeout_seconds=args.timeout,
    )
    print(f"1/5 独立新 Profile：{isolated.get('elapsed_ms')} ms")

    reusable_profile = profiles / "reusable"
    reusable_first = run_conversion(
        name="reusable-profile-first",
        soffice=soffice,
        profile=reusable_profile,
        output_dir=outputs / "reusable-profile-first",
        source=source,
        env=env,
        timeout_seconds=args.timeout,
    )
    print(f"2/5 固定 Profile 首次：{reusable_first.get('elapsed_ms')} ms")
    reusable_second = run_conversion(
        name="reusable-profile-second",
        soffice=soffice,
        profile=reusable_profile,
        output_dir=outputs / "reusable-profile-second",
        source=source,
        env=env,
        timeout_seconds=args.timeout,
    )
    print(f"3/5 固定 Profile 再次：{reusable_second.get('elapsed_ms')} ms")

    persistent = run_persistent_tests(
        soffice=soffice,
        profile=profiles / "persistent",
        output_root=outputs,
        source=source,
        env=env,
        timeout_seconds=args.timeout,
    )
    persistent_results = persistent.get("results", [])
    for index, result in enumerate(persistent_results, start=4):
        print(f"{index}/5 常驻模式 {result['name']}：{result.get('elapsed_ms')} ms")
    if not persistent_results:
        print(f"4-5/5 常驻模式未完成：{persistent.get('error') or 'listener did not become ready'}")

    report = {
        "tool": APP_NAME,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "system": platform.platform(),
        "python": platform.python_version(),
        "soffice": str(soffice),
        "soffice_size": soffice.stat().st_size,
        "document_original": str(document),
        "document_copy": str(source),
        "document_size": source.stat().st_size,
        "document_sha256": sha256_file(source),
        "timeout_seconds": args.timeout,
        "removed_environment_keys": removed_keys,
        "results": [isolated, reusable_first, reusable_second],
        "persistent": persistent,
    }
    report_path = run_root / f"libreoffice-latency-{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text_report_path = run_root / f"libreoffice-latency-{timestamp}.log"
    write_text_report(text_report_path, report)

    print(f"\n报告：{report_path}")
    print(f"日志：{text_report_path}")
    print(f"生成的 PDF：{outputs}")
    print("请把整个本次 logs 目录复制回来。")
    if sys.stdin and sys.stdin.isatty():
        input("\n按 Enter 退出……")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
