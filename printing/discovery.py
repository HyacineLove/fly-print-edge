from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import ipaddress
import logging
import threading
import time
from typing import Any

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .ipp_device import IppPrinterProbe, probe_printer


SERVICE_TYPE = "_ipp._tcp.local."


def _decode_txt(properties: dict[Any, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_value in properties.items():
        key = raw_key.decode("utf-8", errors="replace") if isinstance(raw_key, bytes) else str(raw_key)
        value = raw_value.decode("utf-8", errors="replace") if isinstance(raw_value, bytes) else str(raw_value or "")
        result[key.casefold()] = value
    return result


def _host_for_uri(address: str) -> str:
    return f"[{address}]" if ipaddress.ip_address(address).version == 6 else address


@dataclass(frozen=True)
class DiscoveredService:
    service_name: str
    display_name: str
    ipp_uri: str


class _Listener(ServiceListener):
    def __init__(self, zeroconf: Zeroconf, logger: logging.Logger):
        self.zeroconf, self.logger = zeroconf, logger
        self._items: dict[str, list[DiscoveredService]] = {}
        self._lock = threading.Lock()

    def add_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self._read(service_type, name)

    def update_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self._read(service_type, name)

    def remove_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        with self._lock:
            self._items.pop(name, None)

    def _read(self, service_type: str, name: str) -> None:
        info: ServiceInfo | None = self.zeroconf.get_service_info(service_type, name, timeout=2000)
        if info is None:
            return
        txt = _decode_txt(info.properties)
        resource = txt.get("rp", "").strip()
        if not resource:
            self.logger.warning("IPP service ignored because DNS-SD rp is missing: %s", name)
            return
        if not resource.startswith("/"):
            resource = "/" + resource
        display_name = txt.get("ty") or txt.get("note") or name.removesuffix(f".{service_type}")
        services = [
            DiscoveredService(name, display_name, f"ipp://{_host_for_uri(address)}:{info.port}{resource}")
            for address in sorted(set(info.parsed_addresses()))
        ]
        with self._lock:
            self._items[name] = services

    def snapshot(self) -> list[DiscoveredService]:
        with self._lock:
            return [service for values in self._items.values() for service in values]


class IppDiscovery:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    def discover(self, *, scan_seconds: float = 5.0, probe_timeout: float = 5.0) -> list[dict[str, Any]]:
        zeroconf = Zeroconf()
        listener = _Listener(zeroconf, self.logger)
        browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)
        try:
            time.sleep(scan_seconds)
            services = listener.snapshot()
        finally:
            browser.cancel()
            zeroconf.close()
        if not services:
            return []
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(8, len(services))) as executor:
            futures = {executor.submit(probe_printer, service.ipp_uri, timeout=probe_timeout): service for service in services}
            for future in as_completed(futures):
                service = futures[future]
                try:
                    results.append(future.result().public_dict())
                except Exception as exc:
                    results.append({
                        "name": service.display_name,
                        "type": "ipp",
                        "ipp_uri": service.ipp_uri,
                        "printer_uuid": "",
                        "compatible": False,
                        "issues": [f"IPP 检测失败: {exc}"],
                        "duplex_supported": None,
                        "color_supported": None,
                        "capability_summary": "能力检测失败",
                    })
        deduplicated: dict[str, dict[str, Any]] = {}
        invalid: list[dict[str, Any]] = []
        for item in results:
            identity = str(item.get("printer_uuid") or "")
            if identity:
                deduplicated.setdefault(identity, item)
            else:
                invalid.append(item)
        return sorted([*deduplicated.values(), *invalid], key=lambda item: (str(item.get("name") or "").casefold(), str(item.get("ipp_uri") or "")))

    @staticmethod
    def probe(ipp_uri: str, *, timeout: float = 5.0) -> IppPrinterProbe:
        return probe_printer(ipp_uri, timeout=timeout)
