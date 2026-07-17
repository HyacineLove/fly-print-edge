"""
Portable 临时目录管理
使用项目内的 temp 目录替代系统临时目录，实现完全可移植
"""

import os
from pathlib import Path
import stat
import sys


# 项目根目录（main.py 所在目录）
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 源码模式使用项目目录；PyInstaller 模式使用用户可写的 AppData，避免把
# 运行时文件写入 _internal（该目录主要用于打包 DLL 和只读资源）。
if getattr(sys, "frozen", False):
    _LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA")
    if not _LOCAL_APP_DATA:
        raise RuntimeError("LOCALAPPDATA is required for packaged Edge runtime files")
    _PORTABLE_TEMP_DIR = os.path.join(_LOCAL_APP_DATA, "FlyPrint Edge", "temp")
else:
    _PORTABLE_TEMP_DIR = os.path.join(_PROJECT_ROOT, "temp")


def get_portable_temp_dir():
    """
    获取 portable 临时目录（项目内的 temp 目录）
    如果目录不存在，自动创建
    
    Returns:
        str: 临时目录的绝对路径
    """
    if not os.path.exists(_PORTABLE_TEMP_DIR):
        os.makedirs(_PORTABLE_TEMP_DIR, exist_ok=True)
        # Set permissions to 700 (rwx------) - Owner only
        try:
            os.chmod(_PORTABLE_TEMP_DIR, stat.S_IRWXU)
        except Exception as e:
            print(f" [PortableTemp] 设置权限失败: {e}")
        print(f" [PortableTemp] 创建临时目录: {_PORTABLE_TEMP_DIR}")
    return _PORTABLE_TEMP_DIR


def get_temp_file_path(prefix="tmp", suffix=""):
    """
    生成临时文件路径（在 portable temp 目录内）
    
    Args:
        prefix: 文件名前缀
        suffix: 文件扩展名（如 ".pdf"）
    
    Returns:
        str: 临时文件的绝对路径
    """
    import uuid
    temp_dir = get_portable_temp_dir()
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}{suffix}"
    return os.path.join(temp_dir, filename)


def cleanup_temp_dir(max_age_hours=24):
    """
    清理临时目录中的过期文件
    
    Args:
        max_age_hours: 文件最大存活时间（小时）
    """
    import time

    temp_dir = Path(get_portable_temp_dir())
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0

    def is_expired(path: Path) -> bool:
        try:
            return now - path.stat().st_mtime > max_age_seconds
        except OSError:
            return False

    # Root files are preview/download leftovers created before job-scoped
    # directories were introduced. Known subtrees are cleaned recursively;
    # canonical PDFs and the LibreOffice profile are deliberately excluded.
    for path in temp_dir.iterdir():
        if path.is_file() and is_expired(path):
            try:
                path.unlink()
                cleaned_count += 1
            except OSError:
                pass

    for subtree in (temp_dir / "downloads", temp_dir / "ipp-printing" / "jobs"):
        if not subtree.is_dir():
            continue
        directories = sorted(
            (path for path in subtree.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for path in subtree.rglob("*"):
            if path.is_file() and is_expired(path):
                try:
                    path.unlink()
                    cleaned_count += 1
                except OSError:
                    pass
        for directory in directories:
            if is_expired(directory):
                try:
                    directory.rmdir()
                    cleaned_count += 1
                except OSError:
                    pass

    if cleaned_count > 0:
        print(f" [PortableTemp] 清理 {cleaned_count} 个过期文件")
    return cleaned_count


# 兼容性函数：提供与 tempfile.gettempdir() 相同的接口
def gettempdir():
    """
    获取临时目录（兼容 tempfile.gettempdir()）
    返回项目内的 temp 目录而非系统临时目录
    """
    return get_portable_temp_dir()
