"""
Device-level printer fault probing.

This module intentionally keeps the production path narrow: IPP printer
attributes only. SNMP, EWS, registry, and other exploratory probes belong in
diagnostic tools, not in the cloud job lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Any, Mapping, Optional
from urllib.parse import urlparse
import urllib.request


IPP_PRINTER_STATES = {
    3: "idle",
    4: "processing",
    5: "stopped",
}

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

FAULT_REASON_TOKENS = (
    "media",
    "paper",
    "tray",
    "toner",
    "ink",
    "jam",
    "door",
    "cover",
    "offline",
)


@dataclass(frozen=True)
class PrinterFaultProbeResult:
    available: bool
    faulted: bool
    host: Optional[str] = None
    printer_state: Optional[int] = None
    printer_state_name: str = "unknown"
    printer_state_reasons: list[str] = field(default_factory=list)
    fault_reasons: list[str] = field(default_factory=list)
    accepting_jobs: Optional[bool] = None
    error: str = ""


def resolve_printer_host(printer: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Resolve a configured printer record to a device host for IPP probing."""
    if not printer:
        return None

    for key in ("ip", "ip_address", "host", "hostname", "uri", "location"):
        value = str(printer.get(key) or "").strip()
        if not value:
            continue
        host = _extract_host(value)
        if host:
            return host
    return None


def _extract_host(value: str) -> Optional[str]:
    parsed = urlparse(value)
    if parsed.hostname:
        return parsed.hostname

    parsed = urlparse(f"//{value}")
    if parsed.hostname:
        return parsed.hostname

    if "/" in value or " " in value:
        return None
    return value or None


def ipp_attr(name: str, value: str, tag: int = 0x44) -> bytes:
    name_bytes = name.encode("utf-8")
    value_bytes = value.encode("utf-8")
    return (
        bytes([tag])
        + struct.pack(">H", len(name_bytes))
        + name_bytes
        + struct.pack(">H", len(value_bytes))
        + value_bytes
    )


def build_ipp_get_printer_attributes_request(host: str) -> urllib.request.Request:
    uri = f"ipp://{host}/ipp/print"
    attributes = [
        ipp_attr("attributes-charset", "utf-8", 0x47),
        ipp_attr("attributes-natural-language", "en", 0x48),
        ipp_attr("printer-uri", uri, 0x45),
        ipp_attr("requested-attributes", "printer-state"),
        ipp_attr("", "printer-state-reasons"),
        ipp_attr("", "printer-is-accepting-jobs"),
    ]
    body = b"\x02\x00" + struct.pack(">H", 0x000B) + struct.pack(">I", 1)
    body += b"\x01" + b"".join(attributes) + b"\x03"
    return urllib.request.Request(
        f"http://{host}:631/ipp/print",
        data=body,
        headers={"Content-Type": "application/ipp"},
        method="POST",
    )


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
        return {"error": "response_too_short", "attributes": {}}

    parsed: dict[str, Any] = {
        "version": f"{raw[0]}.{raw[1]}",
        "status_code": int.from_bytes(raw[2:4], "big"),
        "request_id": int.from_bytes(raw[4:8], "big"),
        "groups": [],
        "attributes": {},
    }
    offset = 8
    current_group: Optional[dict[str, Any]] = None
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

        attr = {
            "name": name,
            "tag": tag,
            "tag_name": IPP_VALUE_TAGS.get(tag, f"0x{tag:02x}"),
            "value": decode_ipp_value(tag, value_raw),
        }
        if current_group is not None:
            current_group["attributes"].append(attr)
        parsed["attributes"].setdefault(name, []).append(attr["value"])

    return parsed


class IPPPrinterFaultProbe:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def probe(self, host: Optional[str]) -> PrinterFaultProbeResult:
        if not host:
            return PrinterFaultProbeResult(
                available=False,
                faulted=False,
                error="device_host_unresolved",
            )

        request = build_ipp_get_printer_attributes_request(host)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(4096)
        except Exception as exc:
            return PrinterFaultProbeResult(
                available=False,
                faulted=False,
                host=host,
                error=str(exc),
            )

        parsed = parse_ipp_response(raw)
        attributes = parsed.get("attributes", {})
        state_values = attributes.get("printer-state") or []
        state = state_values[0] if state_values else None
        reasons = [
            str(reason)
            for reason in (attributes.get("printer-state-reasons") or [])
            if str(reason).lower() != "none"
        ]
        accepting_values = attributes.get("printer-is-accepting-jobs") or []
        accepting = accepting_values[0] if accepting_values else None
        fault_reasons = [
            reason
            for reason in reasons
            if any(token in reason.lower() for token in FAULT_REASON_TOKENS)
        ]

        return PrinterFaultProbeResult(
            available=True,
            faulted=state == 5 and bool(fault_reasons),
            host=host,
            printer_state=state,
            printer_state_name=IPP_PRINTER_STATES.get(state, "unknown"),
            printer_state_reasons=reasons or ["none"],
            fault_reasons=fault_reasons,
            accepting_jobs=accepting,
            error=str(parsed.get("error") or parsed.get("parse_error") or ""),
        )
