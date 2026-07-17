"""IPP printer inventory and administration facade."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List
from urllib.parse import urlsplit

from printer_config import PrinterConfig
from printing.discovery import IppDiscovery
from printing.ipp_device import printer_snapshot, printer_status_text, probe_printer
from printing.ipp_protocol import IppClient
from printing.service import DEVICE_JOBS


logger = logging.getLogger(__name__)


class PrinterDiscovery:
    def __init__(self, config: PrinterConfig):
        self.config = config
        self.ipp = IppDiscovery(logger)

    def discover_local_printers(self) -> List[Dict[str, Any]]:
        return []

    def discover_network_printers(self) -> List[Dict[str, Any]]:
        items = self.ipp.discover()
        for item in items:
            printer_uuid = str(item.get("printer_uuid") or "")
            if not printer_uuid or not item.get("compatible"):
                continue
            managed = self.config.get_printer_by_uuid(printer_uuid)
            if managed and managed.get("ipp_uri") != item.get("ipp_uri"):
                logger.info("IPP address updated printer_uuid=%r old=%r new=%r", printer_uuid, managed.get("ipp_uri"), item.get("ipp_uri"))
                self.config.update_ipp_uri(printer_uuid, item["ipp_uri"], item.get("capabilities"))
        return items

    def probe(self, ipp_uri: str):
        return self.ipp.probe(ipp_uri)


class PrinterManager:
    def __init__(self):
        self.config = PrinterConfig()
        self.discovery = PrinterDiscovery(self.config)

    def get_printers(self) -> List[Dict[str, Any]]:
        return self.config.get_managed_printers()

    def _resolve(self, printer_name: str = None, printer_id: str = None) -> Dict[str, Any] | None:
        if printer_id:
            printer = self.config.get_printer_by_id(printer_id)
            if printer:
                return printer
        return self.config.get_printer_by_name(printer_name) if printer_name else None

    def set_printer_enabled(self, printer_id: str, enabled: bool) -> bool:
        return self.config.set_printer_enabled(printer_id, enabled)

    def is_printer_enabled(self, printer_id: str = None, printer_name: str = None) -> bool:
        return self.config.is_printer_enabled(printer_id=printer_id, printer_name=printer_name)

    def probe_printer(self, ipp_uri: str) -> Dict[str, Any]:
        return self.discovery.probe(ipp_uri).public_dict()

    def get_printer_status_detail(self, printer_name: str) -> Dict[str, Any]:
        printer = self._resolve(printer_name=printer_name)
        if not printer:
            return {"status_text": "unknown", "error": "managed printer not found"}
        try:
            snapshot = printer_snapshot(IppClient(printer["ipp_uri"], timeout=5.0))
            return {
                "status_text": printer_status_text(snapshot),
                "ipp": snapshot,
                "ipp_uri": printer["ipp_uri"],
                "printer_uuid": printer["printer_uuid"],
                "uncertain": DEVICE_JOBS.is_uncertain(printer["printer_uuid"]),
            }
        except Exception as exc:
            logger.warning("IPP status query failed printer=%r error=%s", printer_name, exc)
            return {"status_text": "offline", "error": str(exc), "ipp_uri": printer.get("ipp_uri")}

    def get_printer_status(self, printer_name: str) -> str:
        return self.get_printer_status_detail(printer_name)["status_text"]

    def get_print_queue(self, printer_name: str) -> List[Dict[str, Any]]:
        printer = self._resolve(printer_name=printer_name)
        if not printer:
            return []
        detail = self.get_printer_status_detail(printer_name)
        snapshot = detail.get("ipp") or {}
        remote_count = int((snapshot.get("queued-job-count") or [0])[0] or 0)
        count = max(remote_count, DEVICE_JOBS.active_count(printer["printer_uuid"]))
        return [{"source": "ipp", "position": index + 1} for index in range(count)]

    def get_job_status(self, printer_name: str, job_id: int) -> Dict[str, Any]:
        printer = self._resolve(printer_name=printer_name)
        if not printer:
            return {"exists": False}
        from printing.ipp_device import job_snapshot
        return {"exists": True, **job_snapshot(IppClient(printer["ipp_uri"]), int(job_id))}

    def get_printer_capabilities(self, printer_name: str) -> Dict[str, Any]:
        printer = self._resolve(printer_name=printer_name)
        return dict(printer.get("capabilities") or {}) if printer else {}

    def get_admin_printer_summary(self, printer_name: str) -> Dict[str, Any]:
        capabilities = self.get_printer_capabilities(printer_name)
        return {
            "duplex_supported": capabilities.get("duplex_supported"),
            "color_supported": capabilities.get("color_supported"),
            "capability_summary": capabilities.get("capability_summary") or "能力未知",
        }

    def get_printer_port_info(self, printer_name: str) -> Dict[str, Any]:
        printer = self._resolve(printer_name=printer_name)
        if not printer:
            return {}
        parsed = urlsplit(printer["ipp_uri"])
        return {
            "name": printer["name"],
            "protocol": "ipp",
            "host": parsed.hostname or "",
            "port": str(parsed.port or 631),
            "resource": parsed.path,
        }

    def add_printer_intelligently(self, printer_info: Dict[str, Any]) -> tuple[bool, str]:
        ipp_uri = str(printer_info.get("ipp_uri") or "").strip()
        if not ipp_uri:
            return False, "请输入完整的 IPP URI"
        try:
            probe = probe_printer(ipp_uri, timeout=5.0)
        except Exception as exc:
            return False, f"IPP 检测失败: {exc}"
        if not probe.compatible:
            return False, "；".join(probe.issues)
        if self.config.get_printer_by_uuid(probe.printer_uuid):
            return False, "该 IPP 打印机已经在管理列表中"
        record = {
            "name": probe.name,
            "type": "ipp",
            "make_model": probe.make_model,
            "printer_uuid": probe.printer_uuid,
            "ipp_uri": probe.ipp_uri,
            "capabilities": probe.capabilities,
            "capability_checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "enabled": True,
            "cloud_registered": False,
        }
        self.config.add_printer(record)
        return True, f"IPP 打印机 {probe.name} 已添加"

    def clear_uncertain(self, printer_id: str) -> bool:
        printer = self.config.get_printer_by_id(printer_id)
        return bool(printer and DEVICE_JOBS.clear_uncertain(printer.get("printer_uuid", "")))
