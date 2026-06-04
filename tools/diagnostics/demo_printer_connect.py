"""
测试打印机连接方式，找出不触发 Windows "正在等待打印机连接" 弹窗的方法。

在目标机上执行: venv\\Scripts\\python.exe tools\\diagnostics\\demo_printer_connect.py

观察:
  1) 哪种 OpenPrinter 方式不会弹窗
  2) CreatePrinterDC 会不会弹窗
  3) GetPrinter level 2 / level 3 是否正常
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32print
import traceback

# ============================================================
# 配置：改成你的打印机名
# ============================================================
PRINTER_NAME = "HP LaserJet Pro 3288dn"


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_open_printer(name: str, access_rights=None, label: str = ""):
    """测试 OpenPrinter 是否会弹窗"""
    desc = label or f"OpenPrinter(access={access_rights})"
    print(f"\n>>> {desc}")
    try:
        if access_rights is not None:
            h = win32print.OpenPrinter(name, access_rights)
        else:
            h = win32print.OpenPrinter(name)  # 默认权限 —— 可能弹窗！
        print(f"    OK: handle={h}")
        win32print.ClosePrinter(h)
        return True
    except Exception as e:
        print(f"    FAIL: {e}")
        return False


def test_get_printer(name: str, level: int, label: str = ""):
    """测试 GetPrinter，对比不同 level"""
    desc = label or f"GetPrinter(level={level})"
    print(f"\n>>> {desc}")
    h = None
    try:
        h = win32print.OpenPrinter(name, 0x00000008)  # PRINTER_ACCESS_USE
        info = win32print.GetPrinter(h, level)
        if level == 2:
            print(f"    Status (bitmask): {info.get('Status', '?')}")
            print(f"    Attributes:        {info.get('Attributes', '?')}")
            print(f"    pDriverName:       {info.get('pDriverName', '?')}")
            print(f"    pPortName:         {info.get('pPortName', '?')}")
        elif level == 3:
            print(f"    Status (string):   {info.get('Status', '')!r}")
        return info
    except Exception as e:
        print(f"    FAIL: {e}")
        return None
    finally:
        if h:
            win32print.ClosePrinter(h)


def test_enum_jobs(name: str):
    """测试 EnumJobs"""
    print(f"\n>>> EnumJobs({name})")
    h = None
    try:
        h = win32print.OpenPrinter(name, 0x00000008)
        jobs = win32print.EnumJobs(h, 0, -1, 1)
        print(f"    OK: {len(jobs)} 个任务")
        for j in jobs:
            print(f"      JobId={j['JobId']}  Document={j.get('pDocument','?')}  "
                  f"Status={j.get('Status','?')}  Pages={j.get('PagesPrinted','?')}/{j.get('TotalPages','?')}")
        return jobs
    except Exception as e:
        print(f"    FAIL: {e}")
        return []
    finally:
        if h:
            win32print.ClosePrinter(h)


def test_create_printer_dc(name: str):
    """测试 CreatePrinterDC 会不会弹窗（这是最主要的嫌疑人）"""
    print(f"\n>>> CreatePrinterDC({name})  ← 最大嫌疑人!")
    print(f"    如果下面的调用触发了系统弹窗，请手动关闭弹窗后继续...")
    input("    按 Enter 继续...")
    try:
        import win32ui
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(name)
        print(f"    OK: DC created, 未弹窗（或弹窗已处理）")
        # 读一下能力
        import win32con
        dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
        print(f"    DPI X: {dpi_x}")
    except Exception as e:
        print(f"    FAIL: {e}")


def get_wmi_batch():
    """用 PowerShell 批量获取所有打印机状态（无查询限制）"""
    print(f"\n>>> WMI 批量查询 (Get-CimInstance Win32_Printer)")
    import subprocess
    import json
    try:
        cmd = (
            'Get-CimInstance Win32_Printer '
            '| Select-Object Name, WorkOffline, PrinterStatus, '
            'ExtendedPrinterStatus, DetectedErrorState, Availability '
            '| ConvertTo-Json'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10
        )
        if result.returncode != 0:
            print(f"    FAIL: rc={result.returncode}")
            print(f"    stderr={result.stderr.strip()[:300]}")
            return
        items = json.loads(result.stdout.strip()) if result.stdout.strip() else []
        if isinstance(items, dict):
            items = [items]
        print(f"    OK: {len(items)} 台打印机")
        for item in items:
            w = item.get('WorkOffline', '')
            ps = item.get('PrinterStatus', '')
            des = item.get('DetectedErrorState', '')
            name = item.get('Name', '')
            print(f"    {name}")
            print(f"      WorkOffline={w}  PrinterStatus={ps}  DetectedErrorState={des}")
    except Exception as e:
        print(f"    FAIL: {e}")


# ============================================================
# 主流程
# ============================================================
if __name__ == "__main__":
    section("1. 枚举所有系统打印机")
    try:
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        )
        for p in printers:
            name = p[2]
            port = ""
            try:
                h = win32print.OpenPrinter(name, 0x00000008)
                info = win32print.GetPrinter(h, 2)
                win32print.ClosePrinter(h)
                port = info.get('pPortName', '')
            except:
                pass
            marker = " ← 目标!" if PRINTER_NAME in name else ""
            print(f"  {name}  (port={port}){marker}")
    except Exception as e:
        print(f"  FAIL: {e}")

    section("2. 测试不同 OpenPrinter 权限（对比弹窗行为）")
    print("\n  注意：以下测试可能弹出 Windows 系统对话框")
    print("  如果弹窗出现，等待超时或手动取消后继续")

    # 方式 A: 默认权限 —— 最容易弹窗
    test_open_printer(PRINTER_NAME, None, "A) 默认权限（最可能弹窗）")

    # 方式 B: PRINTER_ACCESS_USE (0x08) —— 最小权限
    test_open_printer(PRINTER_NAME, 0x00000008, "B) PRINTER_ACCESS_USE (0x08)")

    # 方式 C: PRINTER_ACCESS_USE + 其他标志
    test_open_printer(PRINTER_NAME, 0x00000008, "C) 再次确认 USE 权限稳定性")

    section("3. GetPrinter 测试（使用 USE 权限）")
    test_get_printer(PRINTER_NAME, 2, "level 2 (Status bitmask)")
    test_get_printer(PRINTER_NAME, 3, "level 3 (Status string)")

    section("4. EnumJobs 测试（使用 USE 权限）")
    test_enum_jobs(PRINTER_NAME)

    section("5. WMI 批量查询（不触发 OpenPrinter）")
    get_wmi_batch()

    section("6. CreatePrinterDC 测试（最大嫌疑人）")
    test_create_printer_dc(PRINTER_NAME)

    section("总结")
    print("""
    请反馈：
    1. 第2步中，哪种 OpenPrinter 方式触发了系统弹窗？
    2. 第6步中，CreatePrinterDC 是否触发了系统弹窗？
    3. 第3/4/5步是否正常完成？

    预期结论：
    - OpenPrinter(0x00000008) 应该不弹窗
    - CreatePrinterDC 大概率会弹窗
    - 如果 CreatePrinterDC 弹窗 → 管理页和打印都需要避开它
    """)
