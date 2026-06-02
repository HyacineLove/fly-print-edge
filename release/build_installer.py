"""
One-click build script for FlyPrint Edge Windows installer.

Orchestrates:
  1. PyInstaller onedir build (via the .spec file)
  2. Copy config.example.json to dist output root (user-facing copy)
  3. Inno Setup installer compilation

Prerequisites:
  - pip install pyinstaller
  - Inno Setup 6+ installed (iscc.exe on PATH or set via INNO_SETUP_DIR)

Usage:
  python release/build_installer.py              # full build
  python release/build_installer.py --skip-pyinstaller  # only rebuild the installer
  python release/build_installer.py --version 2.0.0      # override version
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = PROJECT_ROOT / "flyprint-edge.spec"
ISS_FILE = PROJECT_ROOT / "installer.iss"
DIST_DIR = PROJECT_ROOT / "dist"
EXE_DIR = DIST_DIR / "flyprint-edge"
VBS_FILE = PROJECT_ROOT / "launch.vbs"
CONFIG_EXAMPLE = PROJECT_ROOT / "config.example.json"

# Reasonable defaults for Inno Setup install locations
INNO_SETUP_DIRS = [
    Path(r"C:\Program Files (x86)\Inno Setup 6"),
    Path(r"C:\Program Files\Inno Setup 6"),
]

DEFAULT_VERSION = "1.0.0"


def find_iscc() -> str | None:
    """Locate the Inno Setup compiler (iscc.exe)."""
    # Check explicit PATH first
    result = shutil.which("iscc")
    if result:
        return result

    # Check common install locations
    for d in INNO_SETUP_DIRS:
        candidate = d / "iscc.exe"
        if candidate.is_file():
            return str(candidate)

    return None


def resolve_version(override: str | None = None) -> str:
    """Resolve version from override, env, or edge_node_info module."""
    if override:
        return override.strip()

    env_version = os.environ.get("FLYPRINT_VERSION")
    if env_version:
        return env_version.strip()

    # Try reading from edge_node_info.py
    info_path = PROJECT_ROOT / "edge_node_info.py"
    if info_path.is_file():
        text = info_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("self.version") and '"' in stripped:
                # Extract string between the first pair of double-quotes
                start = stripped.index('"') + 1
                end = stripped.index('"', start)
                return stripped[start:end]

    return DEFAULT_VERSION


def run_pyinstaller(verbose: bool = False) -> int:
    """Build the PyInstaller onedir output."""
    print("=" * 60)
    print("[1/3] Building PyInstaller onedir...")
    print("=" * 60)

    if not SPEC_FILE.is_file():
        print(f"ERROR: Spec file not found: {SPEC_FILE}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--clean",
        "--noconfirm",
    ]
    if verbose:
        cmd.append("--log-level=DEBUG")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed.", file=sys.stderr)
        return result.returncode

    print(f"  -> {EXE_DIR / 'flyprint-edge.exe'}")
    return 0


def copy_config_to_dist() -> None:
    """Copy config.example.json to dist output root so users can find it."""
    if not CONFIG_EXAMPLE.is_file():
        print("WARNING: config.example.json not found — skipping copy.")
        return

    dest = EXE_DIR / "config.example.json"
    shutil.copy2(CONFIG_EXAMPLE, dest)
    print(f"  -> Copied config.example.json to {dest}")


def run_inno_setup(version: str, verbose: bool = False) -> int:
    """Compile the Inno Setup installer."""
    print("=" * 60)
    print(f"[2/3] Building Inno Setup installer ({version})...")
    print("=" * 60)

    iscc = find_iscc()
    if not iscc:
        print("ERROR: Inno Setup compiler (iscc.exe) not found.", file=sys.stderr)
        print("  Install Inno Setup 6+ from: https://jrsoftware.org/isinfo.php", file=sys.stderr)
        return 1

    if not ISS_FILE.is_file():
        print(f"ERROR: Inno Setup script not found: {ISS_FILE}", file=sys.stderr)
        return 1

    if not (EXE_DIR / "flyprint-edge.exe").is_file():
        print(f"ERROR: PyInstaller output not found. Run PyInstaller first.", file=sys.stderr)
        return 1

    # Pass version via define
    cmd = [
        iscc,
        f"/DMyAppVersion={version}",
        str(ISS_FILE),
    ]
    if verbose:
        cmd.append("/V")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("ERROR: Inno Setup build failed.", file=sys.stderr)
        return result.returncode

    return 0


def print_summary(version: str) -> None:
    """Print build result summary."""
    exe_name = f"flyprint-edge-setup-{version}.exe"
    installer = DIST_DIR / exe_name
    print("=" * 60)
    print("[3/3] Build complete!")
    print("=" * 60)
    print(f"  Installer: {installer}")
    if installer.is_file():
        size_mb = installer.stat().st_size / (1024 * 1024)
        print(f"  Size:      {size_mb:.1f} MB")
    print(f"  App dir:   {EXE_DIR}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the FlyPrint Edge Windows installer (PyInstaller + Inno Setup).",
    )
    parser.add_argument(
        "--skip-pyinstaller",
        action="store_true",
        help="Skip the PyInstaller step and only rebuild the Inno Setup installer.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help=f"Version string for the installer filename (default: read from edge_node_info.py or '{DEFAULT_VERSION}').",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output from subcommands.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = resolve_version(args.version)

    if not args.skip_pyinstaller:
        rc = run_pyinstaller(verbose=args.verbose)
        if rc != 0:
            return rc

    copy_config_to_dist()

    rc = run_inno_setup(version, verbose=args.verbose)
    if rc != 0:
        return rc

    print_summary(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
