# Testing Patterns

**Analysis Date:** 2026-03-17

## Test Framework

**Runner:** No formal test framework (pytest/unittest) detected

**Test Execution:** Tests are standalone Python scripts run directly:
```bash
# Run from project root
python tests/test_paper_detection.py
python tests/test_printer_system_check.py
python tests/error_detection_probe.py
```

**Test File Organization:**
- Location: `tests/` directory
- Naming: `test_<feature>.py` or `test_<fix>.py`
- Example files:
  - `tests/test_printer_system_check.py`
  - `tests/test_paper_detection.py`
  - `tests/test_letter_invoice_fix.py`
  - `tests/error_detection_probe.py`

## Test Structure

**Import Pattern:**
All test files use this pattern to import from parent directory:
```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_windows import WindowsEnterprisePrinter
```

**Test Function Pattern:**
```python
def test_pdf_detection():
    """测试 PDF 文件尺寸检测"""
    printer = WindowsEnterprisePrinter()
    
    # Test cases
    test_files = [
        "A4 文档.pdf",
        "Letter 文档.pdf",
    ]
    
    for file_name in test_files:
        if os.path.exists(file_name):
            print(f"\n测试 PDF: {file_name}")
            detected = printer._detect_pdf_page_size(file_name)
            print(f"  检测结果：{detected}")
```

**Main Guard:**
```python
if __name__ == "__main__":
    print("=" * 60)
    print("纸张尺寸自动检测功能测试")
    print("=" * 60)
    
    test_identify_paper_size()
    test_pdf_detection()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
```

## Test Types

**Unit Tests:**
- `test_paper_detection.py` - Tests PDF and Word document paper size detection
- `test_letter_invoice_fix.py` - Tests specific fix for Letter-size invoice printing

**System/Diagnostic Tests:**
- `test_printer_system_check.py` - Lists system printers and checks installation status
- `error_detection_probe.py` - Comprehensive printer error detection monitoring tool

**Test Categories:**

1. **Feature Tests** (`test_paper_detection.py`):
   - Tests specific functions: `_detect_pdf_page_size()`, `_detect_word_document_size()`
   - Uses test data files (when present)
   - Prints pass/fail indicators: `✓` / `✗`

2. **Fix Verification Tests** (`test_letter_invoice_fix.py`):
   - Tests bug fixes and edge cases
   - Scenarios-based testing with explicit expected outcomes
   - Documents the fix with comments

3. **Diagnostic/Probe Tools** (`error_detection_probe.py`):
   - CLI arguments via `argparse`
   - JSON report output
   - Continuous monitoring capabilities
   - Error state detection and categorization

## Test Data

**File-Based Tests:**
- Tests look for files in working directory:
  - `A4 文档.pdf`, `Letter 文档.pdf`, `A3 文档.pdf`
  - `A4 文档.docx`, `Letter 文档.docx`
- Graceful handling of missing files:
```python
for file_name in test_files:
    if os.path.exists(file_name):
        # Run test
    else:
        print(f"\n跳过 (文件不存在): {file_name}")
```

## Test Output

**Visual Format:**
- Separator lines: `print("=" * 60)`
- Chinese language output for test descriptions
- Status indicators: `✓` (pass), `✗` (fail)

**Example Output:**
```
============================================================
纸张尺寸自动检测功能测试
============================================================

测试纸张尺寸识别:
  ✓ 8.27x11.69英寸 -> A4 (期望：A4)
  ✓ 8.5x11.0英寸 -> Letter (期望：Letter)

测试 PDF: test_document.pdf
  检测结果：A4

============================================================
测试完成
============================================================
```

## Advanced Test Pattern (error_detection_probe.py)

**CLI Arguments:**
```python
parser = argparse.ArgumentParser()
parser.add_argument("--printer-name", type=str, default=None)
parser.add_argument("--pdf-path", type=str, default="test.pdf")
parser.add_argument("--trigger-print", action="store_true")
parser.add_argument("--monitor-seconds", type=int, default=180)
parser.add_argument("--output", type=str, default="error_detection_report.json")
```

**Structured Reporting:**
```python
def build_report(...) -> Dict[str, Any]:
    return {
        "success": True,
        "time": now_iso(),
        "platform": platform.platform(),
        "printer_name": printer_name,
        "events": events,
        # ... more fields
    }

def flush_report(path: str, report: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
```

**Event-Driven Testing:**
- Polls printer status in a loop
- Captures events with timestamps
- Detects state changes and anomalies
- Graceful shutdown on KeyboardInterrupt

## Writing New Tests

**Template for Feature Test:**
```python
"""
测试 <功能描述>
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_name import ClassName

def test_feature():
    """测试具体功能"""
    instance = ClassName()
    
    # Test case
    result = instance.method_to_test()
    expected = "expected_value"
    
    if result == expected:
        print(f"  ✓ 测试通过: {result}")
    else:
        print(f"  ✗ 测试失败: 期望 {expected}, 得到 {result}")

if __name__ == "__main__":
    print("=" * 60)
    print("测试标题")
    print("=" * 60)
    test_feature()
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
```

**Where to Add New Tests:**
- Create new file: `tests/test_<feature_name>.py`
- Run from project root: `python tests/test_<feature_name>.py`

## Test Limitations

**Current Gaps:**
- No automated test runner (pytest/unittest)
- No CI/CD test automation
- No code coverage measurement
- Tests require manual execution
- Some tests depend on external files/printers

**Manual Testing Required:**
- Printer hardware availability
- Specific file types (PDF, Word documents)
- Windows platform for printer tests

---

*Testing analysis: 2026-03-17*
