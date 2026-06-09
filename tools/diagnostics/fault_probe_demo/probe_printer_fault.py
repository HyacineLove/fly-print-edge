"""Probe printer/device fault signals for a Windows printer queue.

Run while the printer is normal, then run again while it is out of paper.
Compare stable labels such as win32_printer, cim_printer, get_printer,
snmp_printer_error_state, ipp_printer_state, and hp_ews.

Examples:
  python probe_printer_fault.py --printer "HPIA24DD9 (HP Color LaserJet Pro 3288)"
  python probe_printer_fault.py --printer "HPIA24DD9 (HP Color LaserJet Pro 3288)" --host 192.168.1.50
  python probe_printer_fault.py --printer "HPIA24DD9 (HP Color LaserJet Pro 3288)" --host 192.168.1.50 --watch 5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def log(label: str, **fields: Any) -> None:
    timestamp = dt.datetime.now().isoformat(timespec="seconds")
    rendered = " ".join(f"{key}={value!r}" for key, value in fields.items())
    print(f"{timestamp} fault_probe {label} {rendered}".rstrip(), flush=True)


def run_powershell_json(command: str, timeout: float = 15.0) -> Any:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())
    output = result.stdout.strip()
    if not output:
        return None
    return json.loads(output)


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def probe_win32print(printer_name: str) -> dict[str, Any] | None:
    try:
        import win32print
        import win32timezone  # noqa: F401

        handle = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ACCESS_USE})
        try:
            info2 = win32print.GetPrinter(handle, 2)
            jobs = win32print.EnumJobs(handle, 0, 999, 1) or []
            info3 = None
            try:
                info3 = win32print.GetPrinter(handle, 3)
            except Exception as exc:
                info3 = {"error": str(exc)}
        finally:
            win32print.ClosePrinter(handle)

        snapshot = {
            "name": info2.get("pPrinterName"),
            "driver": info2.get("pDriverName"),
            "port": info2.get("pPortName"),
            "status": info2.get("Status"),
            "attributes": info2.get("Attributes"),
            "info3_status": (info3 or {}).get("Status"),
            "jobs": [
                {
                    "job_id": job.get("JobId"),
                    "document": job.get("pDocument"),
                    "status": job.get("Status"),
                    "status_text": job.get("pStatus"),
                    "pages_printed": job.get("PagesPrinted"),
                    "total_pages": job.get("TotalPages"),
                }
                for job in jobs
            ],
        }
        log("win32_printer", **snapshot)
        return snapshot
    except Exception as exc:
        log("win32_error", error=str(exc))
        return None


def probe_cim_printer(printer_name: str) -> None:
    safe_name = printer_name.replace("'", "''")
    command = (
        f"Get-CimInstance -Query \"SELECT * FROM Win32_Printer WHERE Name='{safe_name}'\" "
        "| Select-Object Name,WorkOffline,PrinterStatus,ExtendedPrinterStatus,"
        "DetectedErrorState,Availability,Status,StatusInfo,PrinterState "
        "| ConvertTo-Json -Depth 4"
    )
    try:
        data = run_powershell_json(command)
        log("cim_printer", data=data)
    except Exception as exc:
        log("cim_error", error=str(exc))


def probe_printmanagement(printer_name: str, port_name: str | None) -> None:
    try:
        data = run_powershell_json(
            "Get-Printer -Name "
            + ps_quote(printer_name)
            + " | Select-Object Name,PrinterStatus,JobCount,Type,DriverName,PortName,Shared,Published "
            + "| ConvertTo-Json -Depth 4"
        )
        log("get_printer", data=data)
    except Exception as exc:
        log("get_printer_error", error=str(exc))

    if not port_name:
        return

    try:
        data = run_powershell_json(
            "Get-PrinterPort -Name "
            + ps_quote(port_name)
            + " | Select-Object * | ConvertTo-Json -Depth 4"
        )
        log("get_printer_port", data=data)
    except Exception as exc:
        log("get_printer_port_error", port=port_name, error=str(exc))


def extract_hosts_from_text(value: Any) -> list[str]:
    text = str(value or "")
    hosts = set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text))
    hosts.update(re.findall(r"https?://([^/:\\\s]+)", text, flags=re.IGNORECASE))
    return sorted(hosts)


def probe_wsd_port_registry(port_name: str | None) -> list[str]:
    if not port_name:
        return []

    try:
        import winreg
    except Exception as exc:
        log("wsd_registry_error", port=port_name, error=str(exc))
        return []

    key_path = rf"SYSTEM\CurrentControlSet\Control\Print\Monitors\WSD Port\Ports\{port_name}"
    values: dict[str, Any] = {}
    hosts: set[str] = set()

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                values[name] = value
                hosts.update(extract_hosts_from_text(value))
                index += 1
    except Exception as exc:
        log("wsd_registry_error", port=port_name, key=key_path, error=str(exc))
        return []

    log("wsd_registry", port=port_name, key=key_path, values=values, host_candidates=sorted(hosts))
    return sorted(hosts)


def http_get(host: str, path: str, timeout: float = 5.0) -> tuple[int | None, str]:
    url = f"http://{host}{path}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "FlyPrintFaultProbe/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096)
            text = body.decode("utf-8", errors="replace")
            return response.status, text
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024).decode("utf-8", errors="replace")
    except Exception as exc:
        return None, str(exc)


def probe_hp_ews(host: str) -> None:
    paths = [
        "/",
        "/DevMgmt/ProductStatusDyn.xml",
        "/DevMgmt/ConsumableStatusDyn.xml",
        "/DevMgmt/ConsumableConfigDyn.xml",
        "/hp/device/DeviceStatus/Index",
    ]
    for path in paths:
        status, text = http_get(host, path)
        interesting = [
            line.strip()
            for line in text.splitlines()
            if any(
                token in line.lower()
                for token in (
                    "paper",
                    "tray",
                    "toner",
                    "supply",
                    "jam",
                    "door",
                    "status",
                    "error",
                )
            )
        ][:20]
        log("hp_ews", host=host, path=path, http_status=status, sample=interesting or text[:300])


def ber_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def ber_tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + ber_len(len(payload)) + payload


def ber_int(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big", signed=False)
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return ber_tlv(0x02, raw)


def ber_octet(value: bytes) -> bytes:
    return ber_tlv(0x04, value)


def ber_null() -> bytes:
    return b"\x05\x00"


def ber_oid(oid: str) -> bytes:
    parts = [int(part) for part in oid.strip(".").split(".")]
    encoded = bytes([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        stack = [part & 0x7F]
        part >>= 7
        while part:
            stack.append(0x80 | (part & 0x7F))
            part >>= 7
        encoded += bytes(reversed(stack))
    return ber_tlv(0x06, encoded)


def snmp_get(host: str, oid: str, community: str = "public", timeout: float = 2.0) -> bytes:
    request_id = int(time.time() * 1000) & 0x7FFFFFFF
    varbind = ber_tlv(0x30, ber_oid(oid) + ber_null())
    varbind_list = ber_tlv(0x30, varbind)
    pdu = ber_tlv(0xA0, ber_int(request_id) + ber_int(0) + ber_int(0) + varbind_list)
    packet = ber_tlv(0x30, ber_int(0) + ber_octet(community.encode("ascii")) + pdu)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (host, 161))
        response, _ = sock.recvfrom(4096)
        return response
    finally:
        sock.close()


def read_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    value = data[offset : offset + length]
    return tag, value, offset + length


def collect_values_by_tag(data: bytes, target_tags: set[int]) -> list[tuple[int, bytes]]:
    matches: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(data):
        try:
            tag, value, next_offset = read_tlv(data, offset)
        except Exception:
            return matches
        if tag in target_tags:
            matches.append((tag, value))
        matches.extend(collect_values_by_tag(value, target_tags))
        offset = next_offset
    return matches


def decode_printer_error_state(raw: bytes) -> list[str]:
    # Printer-MIB bit order is bit 0 = least significant bit of the first octet.
    labels = [
        "low_paper",
        "no_paper",
        "low_toner",
        "no_toner",
        "door_open",
        "jammed",
        "offline",
        "service_requested",
        "input_tray_missing",
        "output_tray_missing",
        "marker_supply_missing",
        "output_near_full",
        "output_full",
        "input_tray_empty",
        "overdue_prevent_maint",
    ]
    active = []
    bit_index = 0
    for byte in raw:
        for mask in (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            if bit_index < len(labels) and byte & mask:
                active.append(labels[bit_index])
            bit_index += 1
    return active


def probe_snmp(host: str, community: str) -> None:
    oids = {
        "sysDescr": "1.3.6.1.2.1.1.1.0",
        "prtGeneralPrinterDetectedErrorState": "1.3.6.1.2.1.43.5.1.1.2.1",
    }
    for name, oid in oids.items():
        try:
            response = snmp_get(host, oid, community=community)
            values = collect_values_by_tag(response, {0x02, 0x04, 0x06, 0x40, 0x41, 0x42, 0x43, 0x44})
            if not values:
                log("snmp_no_value", host=host, oid_name=name, oid=oid, response_hex=response.hex()[:300])
                continue
            value = values[-1]
            tag, raw = value
            if name == "prtGeneralPrinterDetectedErrorState":
                decoded = decode_printer_error_state(raw)
                log("snmp_printer_error_state", host=host, oid=oid, raw_hex=raw.hex(), decoded=decoded)
            else:
                log("snmp_value", host=host, oid_name=name, oid=oid, tag=tag, value=raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            log("snmp_error", host=host, oid_name=name, oid=oid, error=str(exc))


def ipp_attr(name: str, value: str, tag: int = 0x44) -> bytes:
    name_bytes = name.encode("utf-8")
    value_bytes = value.encode("utf-8")
    return bytes([tag]) + struct.pack(">H", len(name_bytes)) + name_bytes + struct.pack(">H", len(value_bytes)) + value_bytes


IPP_GROUP_TAGS = {
    0x01: "operation-attributes",
    0x02: "job-attributes",
    0x04: "printer-attributes",
    0x05: "unsupported-attributes",
}

IPP_VALUE_TAGS = {
    0x21: "integer",
    0x22: "boolean",
    0x23: "enum",
    0x41: "textWithoutLanguage",
    0x42: "nameWithoutLanguage",
    0x44: "keyword",
    0x45: "uri",
    0x47: "charset",
    0x48: "naturalLanguage",
}

IPP_PRINTER_STATES = {
    3: "idle",
    4: "processing",
    5: "stopped",
}


def decode_ipp_value(tag: int, raw: bytes) -> Any:
    if tag in (0x21, 0x23):
        return int.from_bytes(raw, "big", signed=True)
    if tag == 0x22:
        return bool(raw and raw[0])
    if tag in (0x41, 0x42, 0x44, 0x45, 0x47, 0x48):
        return raw.decode("utf-8", errors="replace")
    return raw.hex()


def parse_ipp_response(raw: bytes) -> dict[str, Any]:
    if len(raw) < 8:
        return {"error": "response_too_short", "raw_hex": raw.hex()}

    parsed: dict[str, Any] = {
        "version": f"{raw[0]}.{raw[1]}",
        "status_code": int.from_bytes(raw[2:4], "big"),
        "request_id": int.from_bytes(raw[4:8], "big"),
        "groups": [],
        "attributes": {},
    }
    offset = 8
    current_group: dict[str, Any] | None = None
    last_name = ""

    while offset < len(raw):
        tag = raw[offset]
        offset += 1

        if tag == 0x03:
            break

        if tag in IPP_GROUP_TAGS:
            current_group = {
                "tag": tag,
                "name": IPP_GROUP_TAGS[tag],
                "attributes": [],
            }
            parsed["groups"].append(current_group)
            last_name = ""
            continue

        if offset + 2 > len(raw):
            parsed["parse_error"] = "truncated_name_length"
            break

        name_len = int.from_bytes(raw[offset : offset + 2], "big")
        offset += 2
        name = raw[offset : offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        if name:
            last_name = name
        else:
            name = last_name

        if offset + 2 > len(raw):
            parsed["parse_error"] = "truncated_value_length"
            break

        value_len = int.from_bytes(raw[offset : offset + 2], "big")
        offset += 2
        value_raw = raw[offset : offset + value_len]
        offset += value_len

        value = decode_ipp_value(tag, value_raw)
        attr = {
            "name": name,
            "tag": tag,
            "tag_name": IPP_VALUE_TAGS.get(tag, f"0x{tag:02x}"),
            "value": value,
        }
        if current_group is not None:
            current_group["attributes"].append(attr)

        values = parsed["attributes"].setdefault(name, [])
        values.append(value)

    return parsed


def probe_ipp(host: str) -> None:
    uri = f"ipp://{host}/ipp/print"
    attrs = [
        ipp_attr("attributes-charset", "utf-8", 0x47),
        ipp_attr("attributes-natural-language", "en", 0x48),
        ipp_attr("printer-uri", uri, 0x45),
        ipp_attr("requested-attributes", "printer-state"),
        ipp_attr("", "printer-state-reasons"),
        ipp_attr("", "printer-is-accepting-jobs"),
    ]
    body = b"\x02\x00" + struct.pack(">H", 0x000B) + struct.pack(">I", 1)
    body += b"\x01" + b"".join(attrs) + b"\x03"
    request = urllib.request.Request(
        f"http://{host}:631/ipp/print",
        data=body,
        headers={"Content-Type": "application/ipp"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read(4096)
        parsed = parse_ipp_response(raw)
        attributes = parsed.get("attributes", {})
        state_values = attributes.get("printer-state") or []
        state = state_values[0] if state_values else None
        reasons = attributes.get("printer-state-reasons") or []
        accepting_values = attributes.get("printer-is-accepting-jobs") or []
        accepting = accepting_values[0] if accepting_values else None
        fault_reasons = [
            reason
            for reason in reasons
            if any(token in str(reason).lower() for token in ("media", "paper", "tray", "toner", "jam", "door"))
        ]
        log(
            "ipp_printer_state",
            host=host,
            http_status=200,
            ipp_status_code=parsed.get("status_code"),
            printer_state=state,
            printer_state_name=IPP_PRINTER_STATES.get(state, "unknown"),
            printer_state_reasons=reasons,
            fault_reasons=fault_reasons,
            accepting_jobs=accepting,
            raw_hex=raw.hex()[:300],
        )
        log("ipp_attributes", host=host, attributes=attributes)
    except Exception as exc:
        log("ipp_error", host=host, error=str(exc))


def run_once(args: argparse.Namespace) -> None:
    log("probe_start", printer=args.printer, host=args.host)
    win32_snapshot = probe_win32print(args.printer)
    port_name = win32_snapshot.get("port") if win32_snapshot else None
    probe_cim_printer(args.printer)
    probe_printmanagement(args.printer, port_name)
    host_candidates = probe_wsd_port_registry(port_name)
    hosts = [args.host] if args.host else []
    if args.probe_wsd_hosts:
        hosts.extend(host for host in host_candidates if host not in hosts)
    for host in hosts:
        probe_hp_ews(host)
        probe_snmp(host, args.community)
        probe_ipp(host)
    log("probe_end", printer=args.printer, host=args.host)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Windows and device-level printer fault signals.")
    parser.add_argument("--printer", required=True, help="Exact Windows printer queue name.")
    parser.add_argument("--host", help="Printer IP/hostname for direct HTTP/SNMP/IPP probes.")
    parser.add_argument("--community", default="public", help="SNMP community string.")
    parser.add_argument(
        "--probe-wsd-hosts",
        action="store_true",
        help="Probe host candidates discovered from the WSD port registry.",
    )
    parser.add_argument("--watch", type=float, help="Repeat interval in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.watch:
        while True:
            run_once(args)
            time.sleep(args.watch)
    run_once(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
