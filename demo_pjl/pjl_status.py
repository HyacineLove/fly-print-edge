"""
PJL (Printer Job Language) Status Query Module

Queries HP LaserJet printers for physical device status via PJL commands
sent over TCP port 9100 (JetDirect / RAW protocol).

Supports:
- @PJL INFO STATUS   — device status code + LCD display message + online state
- @PJL INFO PAGECOUNT — total pages printed (lifetime counter)
- @PJL INFO ID        — printer model + firmware info

Status code reference (HP PJL Technical Reference Manual):
  10001 = Ready (online)
  10002 = Offline
  10003 = Warming Up / Initializing
  10004 = Self Test
  10005 = Resetting / Clearing Memory
  10006 = Toner Low
  10023 = Printing
  35078 = Powersave Mode
  400xx = Operator intervention required (paper jam, cover open, etc.)
  50xxx = Hardware errors
"""

import re
import socket
import struct
from typing import Optional, Dict, Any, Tuple


# ── PJL Status Code → Human-readable mapping ──────────────────────────

PJL_STATUS_MAP: Dict[int, str] = {
    # Informational (10xxx)
    10001: "就绪 (Ready)",
    10002: "离线 (Offline)",
    10003: "预热中 (Warming Up)",
    10004: "自检中 (Self Test)",
    10005: "正在复位 (Resetting)",
    10006: "碳粉不足 (Toner Low)",
    10007: "正在取消任务 (Cancelling)",
    10023: "正在打印 (Printing)",
    # Powersave
    35078: "省电模式 (Powersave)",
    # Operator intervention required (40xxx)
    40000: "需要干预 (Intervention Required)",
    40010: "缺纸 (Paper Out)",
    40011: "纸张不足 (Paper Low)",
    40013: "卡纸 (Paper Jam)",
    40015: "盖板打开 (Cover Open)",
    40021: "纸盒问题 (Tray Problem)",
    40022: "定影器错误 (Fuser Error)",
    40023: "盖板或门未关 (Door Open)",
    40024: "纸张尺寸不匹配 (Paper Size Mismatch)",
    40025: "需要维护 (Maintenance Required)",
}

# 40xxx range — generic intervention required
PJL_INTERVENTION_RANGE = range(40000, 50000)
# 50xxx range — hardware errors
PJL_HARDWARE_ERROR_RANGE = range(50000, 60000)


# ── IP Extraction ──────────────────────────────────────────────────────

def extract_ip_from_port_name(port_name: str) -> Optional[str]:
    """Extract IP address from a Windows printer port name.

    Windows names network printer ports in these formats:
      IP_192.168.1.100
      192.168.1.100
      192.168.1.100_1     (with queue suffix)

    Returns the IP address string or None if no IP pattern found.
    """
    if not port_name:
        return None

    # Pattern 1: IP_ prefix (most common for HP Standard TCP/IP ports)
    m = re.search(r'IP[_\s]?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', port_name)
    if m:
        return m.group(1)

    # Pattern 2: bare IP at start (e.g. "192.168.1.100_1")
    m = re.search(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', port_name)
    if m:
        return m.group(1)

    return None


# ── PJL Response Parsing ───────────────────────────────────────────────

def parse_pjl_status_response(response_text: str) -> Optional[Dict[str, Any]]:
    """Parse a PJL @PJL INFO STATUS response into structured data.

    Expected format:
        @PJL INFO STATUS<CR><LF>
        CODE=10001<CR><LF>
        DISPLAY="00 READY"<CR><LF>
        ONLINE=TRUE<CR><LF>
        <FF>

    Returns:
        {
            "code": 10001,
            "display": "00 READY",
            "online": True,
            "status_text": "就绪 (Ready)",
            "category": "ready",       # ready|offline|busy|warning|error|intervention|unknown
            "raw_response": "...",
        }
        or None if the response cannot be parsed as PJL status.
    """
    if not response_text:
        return None

    # Must contain the PJL status response header
    if "@PJL INFO STATUS" not in response_text:
        return None

    code: Optional[int] = None
    display: Optional[str] = None
    online: Optional[bool] = None

    for line in response_text.splitlines():
        line = line.strip()
        if line.startswith("CODE="):
            try:
                code = int(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.startswith("DISPLAY="):
            # Strip surrounding quotes
            display = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("ONLINE="):
            val = line.split("=", 1)[1].strip().upper()
            online = val == "TRUE"

    if code is None and display is None:
        return None

    # Determine status text
    status_text = PJL_STATUS_MAP.get(code or 0)
    if not status_text:
        if code and code in PJL_INTERVENTION_RANGE:
            status_text = f"需要干预 (Intervention: {code})"
        elif code and code in PJL_HARDWARE_ERROR_RANGE:
            status_text = f"硬件错误 (Hardware Error: {code})"
        elif code:
            status_text = f"未知状态 (Unknown: {code})"
        elif display:
            status_text = f"显示: {display}"
        else:
            status_text = "就绪 (Ready)"

    # Categorise
    category = _classify_status(code, online)

    return {
        "code": code,
        "display": display,
        "online": online,
        "status_text": status_text,
        "category": category,
    }


def parse_pjl_pagecount_response(response_text: str) -> Optional[int]:
    """Parse @PJL INFO PAGECOUNT response.

    Expected: @PJL INFO PAGECOUNT\r\nPAGECOUNT=12345\r\n\f
    """
    if not response_text or "@PJL INFO PAGECOUNT" not in response_text:
        return None
    for line in response_text.splitlines():
        if line.startswith("PAGECOUNT="):
            try:
                return int(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                pass
    return None


def parse_pjl_id_response(response_text: str) -> Optional[Dict[str, str]]:
    """Parse @PJL INFO ID response.

    Returns dict with model, firmware, etc.
    """
    if not response_text or "@PJL INFO ID" not in response_text:
        return None
    info: Dict[str, str] = {}
    for line in response_text.splitlines():
        line = line.strip()
        if not line or line.startswith("@PJL") or line == "\f":
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            info[key.strip().strip('"')] = val.strip().strip('"')
        elif '"' in line:
            info["raw"] = line.strip('"')
    return info if info else None


def _classify_status(code: Optional[int], online: Optional[bool]) -> str:
    """Classify the overall printer status into a category."""
    if code is None or code == 10001:
        if online is False:
            return "offline"
        return "ready"
    if code == 10002:
        return "offline"
    if code == 10023:
        return "busy"
    if code == 10003:
        return "busy"  # warming up
    if code and code in PJL_INTERVENTION_RANGE:
        return "intervention"
    if code and code in PJL_HARDWARE_ERROR_RANGE:
        return "error"
    if code and code < 20000:
        return "warning"  # informational / warning
    if online is False:
        return "offline"
    return "unknown"


# ── PJL Socket Communication ───────────────────────────────────────────

def send_pjl_command(ip: str, pjl_command: str, port: int = 9100,
                     timeout: float = 8.0) -> Optional[str]:
    """Send a PJL command to a printer over TCP and return the response.

    Args:
        ip: Printer IP address
        pjl_command: Full PJL command string (including UEL wrappers)
        port: TCP port (default 9100 for JetDirect/RAW)
        timeout: Socket timeout in seconds

    Returns:
        Response text string, or None on any error.
    """
    data = pjl_command.encode('utf-8', errors='replace')

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect((ip, port))
            sock.sendall(data)

            # Read response until UEL terminator seen, or until recv timeout
            response = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    # Stop when UEL command seen (printer has finished responding)
                    if b"%-12345X" in response and len(response) > 50:
                        break
                except socket.timeout:
                    break

        finally:
            try:
                sock.close()
            except Exception:
                pass

        if not response or len(response) < 10:
            return None

        return response.decode('utf-8', errors='replace')

    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return None
    except Exception:
        return None


# ── High-level Status Query ────────────────────────────────────────────

def query_pjl_status(ip: str, port: int = 9100, timeout: float = 8.0
                     ) -> Optional[Dict[str, Any]]:
    """Query printer physical status via PJL INFO STATUS.

    High-level convenience function. Sends @PJL INFO STATUS and returns
    a parsed status dict, or None if the query failed.
    """
    pjl_cmd = "\x1B%-12345X@PJL\r\n@PJL INFO STATUS\r\n\x1B%-12345X"
    response = send_pjl_command(ip, pjl_cmd, port, timeout)
    if response is None:
        return None
    return parse_pjl_status_response(response)


def query_pjl_pagecount(ip: str, port: int = 9100, timeout: float = 8.0
                        ) -> Optional[int]:
    """Query printer total page count via PJL INFO PAGECOUNT."""
    pjl_cmd = "\x1B%-12345X@PJL\r\n@PJL INFO PAGECOUNT\r\n\x1B%-12345X"
    response = send_pjl_command(ip, pjl_cmd, port, timeout)
    if response is None:
        return None
    return parse_pjl_pagecount_response(response)


def query_pjl_id(ip: str, port: int = 9100, timeout: float = 8.0
                 ) -> Optional[Dict[str, str]]:
    """Query printer identification via PJL INFO ID."""
    pjl_cmd = "\x1B%-12345X@PJL\r\n@PJL INFO ID\r\n\x1B%-12345X"
    response = send_pjl_command(ip, pjl_cmd, port, timeout)
    if response is None:
        return None
    return parse_pjl_id_response(response)


def query_pjl_full(ip: str, port: int = 9100, timeout: float = 8.0
                   ) -> Dict[str, Any]:
    """Query all available PJL info from a printer in one call.

    Returns a dict with 'status', 'pagecount', 'id' keys.
    Individual values are None if their query failed.
    """
    result: Dict[str, Any] = {
        "ip": ip,
        "port": port,
        "status": None,
        "pagecount": None,
        "id": None,
    }
    result["status"] = query_pjl_status(ip, port, timeout)
    result["pagecount"] = query_pjl_pagecount(ip, port, timeout)
    result["id"] = query_pjl_id(ip, port, timeout)
    return result


# ── Windows Printer Integration Helpers ────────────────────────────────

def get_printer_ip_windows(printer_name: str) -> Optional[str]:
    """Get a printer's IP address using the Windows print spooler API.

    Requires pywin32 to be installed. Returns the IP string or None.
    """
    try:
        import win32print
    except ImportError:
        return None

    try:
        handle = win32print.OpenPrinter(printer_name)
        info = win32print.GetPrinter(handle, 2)
        win32print.ClosePrinter(handle)
        port_name = info.get('pPortName', '')
        return extract_ip_from_port_name(port_name)
    except Exception:
        return None


def query_printer_status_windows(printer_name: str, timeout: float = 8.0
                                 ) -> Optional[Dict[str, Any]]:
    """Query PJL status for a Windows printer by name.

    Extracts the IP from the printer's port configuration, then queries
    via PJL. Returns None if the printer is not a network printer or if
    PJL query fails.
    """
    ip = get_printer_ip_windows(printer_name)
    if not ip:
        return None
    return query_pjl_status(ip, timeout=timeout)


def discover_network_printers_windows() -> list:
    """Discover all Windows printers that have IP-based ports.

    Returns a list of dicts: {name, ip, port_name}
    """
    printers: list = []
    try:
        import win32print
    except ImportError:
        return printers

    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        for entry in win32print.EnumPrinters(flags):
            printer_name = entry[2]
            try:
                handle = win32print.OpenPrinter(printer_name)
                info = win32print.GetPrinter(handle, 2)
                win32print.ClosePrinter(handle)
                port_name = info.get('pPortName', '')
                ip = extract_ip_from_port_name(port_name)
                if ip:
                    printers.append({
                        "name": printer_name,
                        "ip": ip,
                        "port_name": port_name,
                        "driver": info.get('pDriverName', ''),
                    })
            except Exception:
                continue
    except Exception:
        pass

    return printers
