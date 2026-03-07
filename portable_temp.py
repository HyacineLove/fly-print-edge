"""
Portable 临时目录管理
使用项目内的 temp 目录替代系统临时目录，实现完全可移植
"""

import os
import stat
import tempfile


# 项目根目录（main.py 所在目录）
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Portable 临时目录（项目内）
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
    import glob
    
    temp_dir = get_portable_temp_dir()
    if not os.path.exists(temp_dir):
        return
    
    pattern = os.path.join(temp_dir, "*")
    files = glob.glob(pattern)
    
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0
    
    for file_path in files:
        try:
            if os.path.isfile(file_path):
                file_age = now - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    os.remove(file_path)
                    cleaned_count += 1
        except Exception as e:
            # 忽略单个文件清理失败
            pass
    
    if cleaned_count > 0:
        print(f" [PortableTemp] 清理 {cleaned_count} 个过期文件")


# 兼容性函数：提供与 tempfile.gettempdir() 相同的接口
def gettempdir():
    """
    获取临时目录（兼容 tempfile.gettempdir()）
    返回项目内的 temp 目录而非系统临时目录
    """
    return get_portable_temp_dir()
