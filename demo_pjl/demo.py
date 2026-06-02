#!/usr/bin/env python
"""
PJL Printer Status Demo — Interactive CLI Tool

Usage:
    python demo_pjl/demo.py                  # Interactive mode
    python demo_pjl/demo.py <ip_or_name>     # Quick query a printer
    python demo_pjl/demo.py --scan           # Scan Windows for network printers
    python demo_pjl/demo.py --raw <ip>       # Raw PJL command mode

Examples:
    python demo_pjl/demo.py 192.168.1.100          # query by IP
    python demo_pjl/demo.py "HP LaserJet Pro 3288"  # query by Windows name
    python demo_pjl/demo.py --scan                   # discover network printers
"""

import sys
import os
import time

# Allow running from project root: python demo_pjl/demo.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pjl_status import (
    query_pjl_status,
    query_pjl_pagecount,
    query_pjl_id,
    query_pjl_full,
    query_printer_status_windows,
    discover_network_printers_windows,
    extract_ip_from_port_name,
    send_pjl_command,
    parse_pjl_status_response,
    PJL_STATUS_MAP,
)


# ── Formatting helpers ─────────────────────────────────────────────────

# Force UTF-8 for Windows GBK terminals
import io
try:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

CATEGORY_ICONS = {
    "ready":        f"{GREEN}[OK]{RESET}",
    "busy":         f"{CYAN}[..]{RESET}",
    "offline":      f"{RED}[OFF]{RESET}",
    "warning":      f"{YELLOW}[!!]{RESET}",
    "intervention": f"{RED}[XX]{RESET}",
    "error":        f"{RED}[XX]{RESET}",
    "unknown":      f"{YELLOW}[??]{RESET}",
}

CATEGORY_COLORS = {
    "ready":        GREEN,
    "busy":         CYAN,
    "offline":      RED,
    "warning":      YELLOW,
    "intervention": RED,
    "error":        RED,
    "unknown":      YELLOW,
}


def print_header(title: str):
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")


def print_status(result: dict):
    """Pretty-print a PJL status result."""
    if not result:
        print(f"  {RED}查询失败 — 无响应{RESET}")
        return

    code = result.get("code")
    display = result.get("display")
    online = result.get("online")
    status_text = result.get("status_text", "?")
    category = result.get("category", "unknown")

    icon = CATEGORY_ICONS.get(category, CATEGORY_ICONS["unknown"])
    color = CATEGORY_COLORS.get(category, RESET)

    print(f"  {icon} {color}{BOLD}{status_text}{RESET}")
    if code is not None:
        print(f"    PJL Code : {code}")
    if display is not None:
        print(f"    Display  : \"{display}\"")
    print(f"    Online   : {GREEN}Yes{RESET}" if online else f"    Online   : {RED}No{RESET}")
    print(f"    Category : {category}")


def print_pagecount(count):
    if count is not None:
        print(f"    Total Pages Printed : {BOLD}{count:,}{RESET}")
    else:
        print(f"    Total Pages Printed : {YELLOW}N/A{RESET}")


def print_id(info: dict):
    if not info:
        print(f"    {YELLOW}设备信息 : N/A{RESET}")
        return
    for key, val in info.items():
        print(f"    {key:20s} : {val}")


# ── Interactive mode ───────────────────────────────────────────────────

def interactive_mode():
    """Interactive PJL printer status query mode."""
    print_header("PJL 打印机状态查询工具")
    print(f"  {CYAN}HP LaserJet Pro 3288 状态追踪 — PJL 协议验证{RESET}")

    # First, try to discover Windows network printers
    try:
        network_printers = discover_network_printers_windows()
    except Exception:
        network_printers = []

    if network_printers:
        print(f"\n  {BOLD}发现 {len(network_printers)} 台网络打印机:{RESET}\n")
        for i, p in enumerate(network_printers, 1):
            print(f"  [{i}] {p['name']}")
            print(f"      IP: {p['ip']}  |  Port: {p['port_name']}  |  Driver: {p['driver']}")

        print(f"\n  [0] 手动输入 IP 地址")
        print(f"  [q] 退出")

        while True:
            choice = input(f"\n  {BOLD}请选择打印机 [{RESET}1-{len(network_printers)}/0/q{BOLD}]: {RESET}").strip()
            if choice.lower() == 'q':
                print(f"\n  Goodbye!\n")
                return
            if choice == '0':
                ip = input("  IP 地址: ").strip()
                if ip:
                    query_by_ip(ip)
                continue
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(network_printers):
                    query_printer(network_printers[idx])
                else:
                    print(f"  {RED}无效选择{RESET}")
            except ValueError:
                print(f"  {RED}无效输入{RESET}")
    else:
        print(f"\n  {YELLOW}未发现网络打印机（pywin32 可能未安装或没有网络打印机）{RESET}")
        print(f"  请手动输入 IP 地址\n")
        ip = input(f"  {BOLD}IP 地址{RESET} (回车退出): ").strip()
        if ip:
            query_by_ip(ip)
        else:
            print(f"\n  Goodbye!\n")


def query_printer(p: dict):
    """Query and display full info for a discovered printer."""
    print_header(f"查询: {p['name']}")
    print(f"  IP   : {p['ip']}")
    print(f"  Port : {p['port_name']}")
    print(f"  Model: {p.get('driver', 'N/A')}")
    print()

    t0 = time.perf_counter()
    result = query_pjl_full(p['ip'])
    elapsed = time.perf_counter() - t0

    print(f"  {BOLD}─ 状态 ─────────────────────────────{RESET}")
    print_status(result.get("status"))

    print(f"\n  {BOLD}─ 计数 ─────────────────────────────{RESET}")
    print_pagecount(result.get("pagecount"))

    print(f"\n  {BOLD}─ 设备 ─────────────────────────────{RESET}")
    print_id(result.get("id"))

    print(f"\n  {CYAN}查询耗时: {elapsed*1000:.0f} ms{RESET}")
    print()


def query_by_ip(ip: str):
    """Query a printer by direct IP address."""
    print_header(f"查询 IP: {ip}")

    t0 = time.perf_counter()
    result = query_pjl_full(ip)
    elapsed = time.perf_counter() - t0

    print(f"  {BOLD}─ 状态 ─────────────────────────────{RESET}")
    print_status(result.get("status"))

    print(f"\n  {BOLD}─ 计数 ─────────────────────────────{RESET}")
    print_pagecount(result.get("pagecount"))

    print(f"\n  {BOLD}─ 设备 ─────────────────────────────{RESET}")
    print_id(result.get("id"))

    print(f"\n  {CYAN}查询耗时: {elapsed*1000:.0f} ms{RESET}")
    print()


# ── Scan mode ──────────────────────────────────────────────────────────

def scan_mode():
    """Scan all Windows network printers and show their status."""
    print_header("扫描网络打印机")

    try:
        printers = discover_network_printers_windows()
    except Exception as e:
        print(f"  {RED}扫描失败: {e}{RESET}\n")
        return

    if not printers:
        print(f"  {YELLOW}未发现任何网络打印机{RESET}")
        print(f"  可能原因: 没有 IP 端口打印机, 或 pywin32 未安装\n")
        return

    print(f"  发现 {len(printers)} 台网络打印机\n")

    for p in printers:
        print(f"  {BOLD}{p['name']}{RESET}  ({p['ip']})")
        result = query_pjl_status(p['ip'])
        if result:
            print_status(result)
        else:
            print(f"    {RED}PJL 查询失败 — 打印机可能离线或不支持 PJL{RESET}")
        print()

    print(f"  扫描完成\n")


# ── Raw command mode ───────────────────────────────────────────────────

def raw_mode(ip: str):
    """Send raw PJL commands interactively."""
    print_header(f"Raw PJL Mode — {ip}")
    print(f"  输入 PJL 命令 (不含 UEL 包装, 输入 'quit' 退出):\n")

    while True:
        try:
            cmd = input(f"  {BOLD}PJL>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  Goodbye!\n")
            return

        if not cmd:
            continue
        if cmd.lower() in ('quit', 'exit', 'q'):
            print(f"\n  Goodbye!\n")
            return

        # Wrap in UEL
        full_cmd = f"\x1B%-12345X@PJL\r\n{cmd}\r\n\x1B%-12345X"
        response = send_pjl_command(ip, full_cmd)

        if response:
            print(f"\n{CYAN}{response}{RESET}\n")
        else:
            print(f"\n  {RED}无响应{RESET}\n")


# ── Quick mode ─────────────────────────────────────────────────────────

def quick_mode(target: str):
    """Quick query — auto-detect if target is IP or printer name."""
    # Check if it looks like an IP address
    ip = extract_ip_from_port_name(f"IP_{target}") or extract_ip_from_port_name(target)
    if ip:
        query_by_ip(ip)
        return

    # Try as Windows printer name
    print_header(f"查询打印机: {target}")
    print(f"  正在解析 IP...")

    ip = None
    try:
        import win32print
        handle = win32print.OpenPrinter(target)
        info = win32print.GetPrinter(handle, 2)
        win32print.ClosePrinter(handle)
        port_name = info.get('pPortName', '')
        ip = extract_ip_from_port_name(port_name)
        print(f"  Port: {port_name}")
        print(f"  IP  : {ip or '无法解析'}")
    except Exception as e:
        print(f"  {RED}无法打开打印机: {e}{RESET}")

    if ip:
        print()
        query_by_ip(ip)
    else:
        print(f"\n  {RED}无法从打印机名称解析 IP 地址{RESET}")
        print(f"  请使用 IP 地址直接查询: python demo_pjl/demo.py <IP>\n")


# ── Test mode ──────────────────────────────────────────────────────────

def test_mode():
    """Run unit-level tests on parsing functions (no printer needed)."""
    print_header("PJL 解析器单元测试 (无需物理打印机)")

    tests = []

    # Test IP extraction
    tests.append(("extract_ip IP_ prefix", extract_ip_from_port_name("IP_192.168.1.100"), "192.168.1.100"))
    tests.append(("extract_ip with suffix", extract_ip_from_port_name("192.168.1.100_1"), "192.168.1.100"))
    tests.append(("extract_ip bare", extract_ip_from_port_name("192.168.1.100"), "192.168.1.100"))
    tests.append(("extract_ip USB", extract_ip_from_port_name("USB001"), None))
    tests.append(("extract_ip LPT", extract_ip_from_port_name("LPT1:"), None))
    tests.append(("extract_ip WSD", extract_ip_from_port_name("WSD-abc-123"), None))
    tests.append(("extract_ip empty", extract_ip_from_port_name(""), None))
    tests.append(("extract_ip None", extract_ip_from_port_name(None), None))

    # Test PJL response parsing
    ready_resp = "@PJL INFO STATUS\r\nCODE=10001\r\nDISPLAY=\"00 READY\"\r\nONLINE=TRUE\r\n\x1B%-12345X"
    parsed = parse_pjl_status_response(ready_resp)
    tests.append(("parse ready code", parsed["code"] if parsed else None, 10001))
    tests.append(("parse ready display", parsed["display"] if parsed else None, "00 READY"))
    tests.append(("parse ready online", parsed["online"] if parsed else None, True))
    tests.append(("parse ready category", parsed["category"] if parsed else None, "ready"))

    toner_resp = "@PJL INFO STATUS\r\nCODE=10006\r\nDISPLAY=\"16 TONER LOW\"\r\nONLINE=TRUE\r\n\f"
    parsed2 = parse_pjl_status_response(toner_resp)
    tests.append(("parse toner code", parsed2["code"] if parsed2 else None, 10006))
    tests.append(("parse toner category", parsed2["category"] if parsed2 else None, "warning"))

    jam_resp = "@PJL INFO STATUS\r\nCODE=40013\r\nDISPLAY=\"13.1 PAPER JAM\"\r\nONLINE=FALSE\r\n\f"
    parsed3 = parse_pjl_status_response(jam_resp)
    tests.append(("parse jam code", parsed3["code"] if parsed3 else None, 40013))
    tests.append(("parse jam category", parsed3["category"] if parsed3 else None, "intervention"))
    tests.append(("parse jam online", parsed3["online"] if parsed3 else None, False))

    garbage = "HTTP/1.1 404 Not Found\r\n\r\n"
    tests.append(("parse garbage", parse_pjl_status_response(garbage), None))

    empty = ""
    tests.append(("parse empty", parse_pjl_status_response(empty), None))

    # Run
    passed = 0
    failed = 0
    for name, got, expected in tests:
        if got == expected:
            print(f"  {GREEN}PASS{RESET} {name}")
            passed += 1
        else:
            print(f"  {RED}FAIL{RESET} {name}  expected={expected!r}  got={got!r}")
            failed += 1

    print(f"\n  {BOLD}{passed} passed, {failed} failed{RESET}\n")

    # Print status code table
    print_header("PJL 状态码参考表")
    for code, text in sorted(PJL_STATUS_MAP.items()):
        print(f"  {code:>6} → {text}")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--scan":
            scan_mode()
        elif arg == "--raw":
            if len(sys.argv) > 2:
                raw_mode(sys.argv[2])
            else:
                print("Usage: python demo_pjl/demo.py --raw <ip>")
        elif arg == "--test":
            test_mode()
        else:
            quick_mode(arg)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
