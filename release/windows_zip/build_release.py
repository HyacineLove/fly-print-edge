from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


PACKAGE_NAME = "flyprint-edge-win-x64"
ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
APP_FILES = (
    "cloud_api_client.py",
    "cloud_auth.py",
    "cloud_heartbeat_service.py",
    "cloud_service.py",
    "cloud_websocket_client.py",
    "config.example.json",
    "config_service.py",
    "edge_node_info.py",
    "file_manager.py",
    "interactive_session.py",
    "logging_utils.py",
    "main.py",
    "portable_temp.py",
    "printer_config.py",
    "printer_linux.py",
    "printer_parsers.py",
    "printer_utils.py",
    "printer_windows.py",
    "requirements.txt",
)
APP_DIRS = ("static",)
ROOT_TEMPLATE_FILES = ("README-runtime.md", "start-edge.cmd", "start-edge-debug.cmd")
SCRIPT_TEMPLATE_FILES = ("bootstrap.ps1", "launch.ps1")
EMPTY_DIRS = ("logs", "temp")


def ensure_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"required path is missing: {path}")


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_file(source: Path, destination: Path) -> None:
    ensure_exists(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    ensure_exists(source)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def write_zip_from_directory(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source_dir, source_dir.name + "/")
        for path in sorted(source_dir.rglob("*")):
            arcname = Path(source_dir.name) / path.relative_to(source_dir)
            if path.is_dir():
                if not any(path.iterdir()):
                    archive.write(path, str(arcname).replace("\\", "/") + "/")
                continue
            archive.write(path, str(arcname).replace("\\", "/"))


def build_release(project_root: Path, output_root: Path, package_name: str = PACKAGE_NAME) -> tuple[Path, Path]:
    release_dir = output_root / package_name
    app_dir = release_dir / "app"
    scripts_dir = release_dir / "scripts"
    zip_path = output_root / f"{package_name}.zip"

    reset_dir(release_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    app_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    for relative_name in APP_FILES:
        copy_file(project_root / relative_name, app_dir / relative_name)

    for relative_name in APP_DIRS:
        copy_tree(project_root / relative_name, app_dir / relative_name)

    for relative_name in ROOT_TEMPLATE_FILES:
        copy_file(TEMPLATES_DIR / relative_name, release_dir / relative_name)

    for relative_name in SCRIPT_TEMPLATE_FILES:
        copy_file(TEMPLATES_DIR / "scripts" / relative_name, scripts_dir / relative_name)

    for relative_name in EMPTY_DIRS:
        (release_dir / relative_name).mkdir(parents=True, exist_ok=True)

    write_zip_from_directory(release_dir, zip_path)
    return release_dir, zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the FlyPrint Edge Windows zip release.")
    parser.add_argument(
        "--output-root",
        default="dist/windows-zip",
        help="Directory used for the assembled release folder and zip archive.",
    )
    parser.add_argument(
        "--package-name",
        default=PACKAGE_NAME,
        help="Name of the generated release folder and zip archive.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = ROOT.parent.parent
    output_root = (project_root / args.output_root).resolve()
    release_dir, zip_path = build_release(project_root, output_root, args.package_name)
    print(f"Release directory: {release_dir}")
    print(f"Release archive:   {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
