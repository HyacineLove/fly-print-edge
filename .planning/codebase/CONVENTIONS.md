# Coding Conventions

**Analysis Date:** 2026-03-17

## Overview

This is a Python-based edge printing service for FlyPrint Cloud. The codebase follows Python conventions with Chinese language support for user-facing messages.

## Naming Patterns

**Files:**
- Use `snake_case` for all Python files
- Module naming pattern: `<domain>_<submodule>.py` (e.g., `printer_config.py`, `cloud_service.py`, `cloud_websocket_client.py`)
- Test files: `test_<feature>.py` (e.g., `test_paper_detection.py`)

**Classes:**
- Use `PascalCase` for class names
- Examples: `PrinterConfig`, `CloudService`, `CloudWebSocketClient`, `PrinterManager`
- Abstract base classes: Descriptive name with `Parser` suffix (e.g., `PrinterParameterParser`)

**Functions/Methods:**
- Use `snake_case` for all functions
- Private methods: prefix with `_` (e.g., `_load_settings`, `_cleanup_loop`)
- Getter/Setter pattern: `get_<property>()`, `set_<property>()` (e.g., `get_printers()`, `set_default_printer_id()`)

**Variables:**
- Use `snake_case` for variables
- Module-level constants: `UPPER_CASE` (e.g., `WIN32_AVAILABLE`, `WMI_AVAILABLE`)
- Type hints encouraged: `printer_manager: Optional[PrinterManager] = None`
- Global variables declared at module level with type annotations

**Dictionary Keys:**
- Use `snake_case` for JSON/config keys (e.g., `"managed_printers"`, `"default_printer_id"`)

## Code Style

**Formatting:**
- No formal formatter configured (no `.prettierrc`, `black.toml`, etc.)
- Indentation: 4 spaces
- Line length: Not strictly enforced, but keep under ~120 characters
- Trailing whitespace: Not strictly managed

**Import Organization:**

Standard order (observed in `main.py`, `cloud_service.py`):
```python
# 1. Standard library
import os
import sys
import json
import time
from typing import Dict, Any, Optional

# 2. Third-party libraries
import uvicorn
import requests
from fastapi import FastAPI, Request
from PIL import Image

# 3. Local modules
from printer_utils import PrinterManager
from cloud_service import CloudService
```

**Import Style:**
- Use absolute imports with module path: `from printer_config import PrinterConfig`
- Platform-conditional imports for Windows-specific modules:
```python
if platform.system() == "Windows":
    try:
        import win32print
        import win32api
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
```

## Error Handling

**Primary Pattern:** Return result dictionaries with success flag:
```python
def submit_print_job(self, ...) -> Dict[str, Any]:
    try:
        # ... do work ...
        return {"success": True, "message": "打印任务已提交"}
    except Exception as e:
        print(f" 提交打印任务时出错: {e}")
        return {"success": False, "message": f"提交打印任务时出错: {e}"}
```

**Exception Handling:**
- Always wrap platform-specific calls in try/except
- Log errors with print statements (Chinese language): `print(f" [ERROR] 连接失败: {e}")`
- Use traceback for detailed debugging:
```python
import traceback
error_detail = traceback.format_exc()
print(f" [DEBUG] 错误详情:\n{error_detail}")
```

**HTTP Error Handling:**
- Return JSONResponse with status codes for API endpoints
- Pattern: `JSONResponse(status_code=503, content={"success": False, "message": "..."})`

## Logging

**Framework:** Use Python's built-in `logging` module and `print()` statements

**Log Levels (observed):**
- `[INFO]` - General information
- `[DEBUG]` - Debug information (extensive throughout codebase)
- `[WARNING]` - Warnings
- `[ERROR]` - Errors

**Log Format:**
```python
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EdgeServer")
```

**Print Prefix Convention:**
- `[FileManager]` - Module-specific prefix
- `[DEBUG]`, `[INFO]`, `[WARNING]`, `[ERROR]` - Severity prefix
- Chinese messages for user-facing logs

## Function Design

**Size:** Functions tend to be medium-length (20-50 lines). Complex operations are split into helper methods.

**Parameters:**
- Use type hints for all function signatures
- Default values for optional parameters: `def __init__(self, config_file="config.json"):`
- Use `Optional[Type]` for nullable parameters

**Return Values:**
- Return dictionaries with structured results for complex operations
- Return tuples for multiple values: `-> tuple[bool, str]`
- Use `Optional[Type]` for functions that may return None

**Example Pattern:**
```python
def add_printer_intelligently(self, printer_info: Dict[str, Any]) -> tuple[bool, str]:
    """智能添加打印机（自动处理网络打印机）"""
    try:
        # ... implementation ...
        return True, f"打印机 {printer_name} 添加成功"
    except Exception as e:
        return False, f"添加失败: {str(e)}"
```

## Comments and Docstrings

**Module Docstrings:**
```python
"""
打印机配置管理
负责配置文件的读写和打印机列表管理
"""
```

**Class Docstrings:**
```python
class PrinterConfig:
    """打印机配置管理"""
```

**Function Docstrings:**
- Brief Chinese description
- Args section for parameters
- Returns section for return values (when complex)

```python
def register_preview_file(self, file_id: str, file_path: str, pdf_path: Optional[str] = None):
    """
    注册预览文件
    
    Args:
        file_id: 文件ID
        file_path: 原始文件路径
        pdf_path: PDF转换文件路径（如果有）
    """
```

**Inline Comments:**
- Use Chinese for business logic comments
- Use English for technical implementation notes
- Debug print statements frequently used as inline documentation

## Module Structure

**File Organization Pattern:**
1. Module docstring
2. Imports (standard lib, third-party, local)
3. Constants/Module-level variables
4. Class definitions
5. Function definitions (if module-level)
6. Entry point guard: `if __name__ == "__main__":`

**Class Organization:**
```python
class CloudService:
    """云端服务管理器"""
    
    def __init__(self, ...):
        # Initialize attributes
        
    def public_method(self, ...):
        # Public API
        
    def _private_method(self, ...):
        # Internal implementation
```

## Configuration

**Configuration File:** `config.json` (user-specific, gitignored)
**Template:** `config.example.json`

**Configuration Pattern:**
```python
def _load_settings(self) -> Dict[str, Any]:
    candidates = [
        os.path.join(os.getcwd(), "config.json"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))
    ]
    for config_path in candidates:
        if not os.path.exists(config_path):
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("settings", {})
        except Exception:
            return {}
    return {}
```

## Threading Patterns

**Daemon Threads:**
```python
def start(self):
    if self.running:
        return
    self.running = True
    self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
    self.thread.start()
```

**Thread Safety:**
- Use `threading.Lock()` for shared state
- Pattern observed: `self.preview_lock = threading.Lock()`

## Platform Abstraction

**Pattern:**
```python
if platform.system() == "Windows":
    from printer_windows import WindowsEnterprisePrinter
    self.platform_printer = WindowsEnterprisePrinter()
else:
    from printer_linux import LinuxPrinter
    self.platform_printer = LinuxPrinter()
```

## Async Patterns

**Asyncio Integration:**
```python
def _run_async_loop(self):
    """在单独线程中运行异步循环"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    self.loop = loop
    try:
        loop.run_until_complete(self._connect_and_listen())
    except Exception as e:
        print(f" [ERROR] WebSocket异步循环异常: {e}")
    finally:
        loop.close()
```

---

*Convention analysis: 2026-03-17*
