"""Local printer fault state and user-facing reason mapping."""

from __future__ import annotations

from copy import deepcopy
import threading
import time
from typing import Any, Iterable, Optional


FAULT_GROUPS = [
    (
        "media-empty-error",
        "缺纸",
        "打印机缺纸，请联系管理员补纸",
        {"media-empty-error", "media-needed-error", "media-empty-warning"},
    ),
    (
        "media-jam-error",
        "卡纸",
        "打印机卡纸，请联系管理员处理",
        {"media-jam-error", "paper-jam-error"},
    ),
    (
        "toner-empty-error",
        "耗材不足",
        "打印机耗材不足，请联系管理员更换耗材",
        {"toner-empty-error", "marker-supply-empty-error", "marker-supply-low-warning"},
    ),
    (
        "door-open-error",
        "机盖未关闭",
        "打印机机盖未关闭，请联系管理员检查",
        {"door-open-error", "cover-open-error"},
    ),
    (
        "tray-missing-error",
        "纸盒未就位",
        "打印机纸盒未安装或未就位，请联系管理员检查",
        {"tray-missing-error", "media-tray-missing-error"},
    ),
]

STICKY_FAULT_REASON_FAMILIES = (
    ("media", "paper"),
    ("jam",),
    ("toner", "ink", "marker-supply"),
    ("door", "cover"),
    ("tray",),
    ("offline",),
)

STILL_FAULT_LIKE_TOKENS = (
    "empty",
    "needed",
    "jam",
    "low",
    "open",
    "missing",
    "offline",
    "error",
    "warning",
    "report",
)


def _normalize_reasons(reasons: Optional[Iterable[Any]]) -> list[str]:
    normalized = []
    for reason in reasons or []:
        text = str(reason or "").strip()
        if text and text.lower() != "none":
            normalized.append(text)
    return normalized


def _lower_reason_set(reasons: Optional[Iterable[Any]]) -> set[str]:
    return {reason.lower() for reason in _normalize_reasons(reasons)}


def _has_family_reason(reasons: set[str], family: tuple[str, ...]) -> bool:
    return any(any(token in reason for token in family) for reason in reasons)


def _still_reports_fault(reasons: set[str], family: tuple[str, ...]) -> bool:
    return any(
        any(token in reason for token in family)
        and any(marker in reason for marker in STILL_FAULT_LIKE_TOKENS)
        for reason in reasons
    )


def map_ipp_fault_reasons(reasons: Optional[Iterable[Any]]) -> dict[str, Any]:
    raw_reasons = _normalize_reasons(reasons)
    reason_set = {reason.lower() for reason in raw_reasons}
    for code, label, message, group in FAULT_GROUPS:
        if reason_set & group:
            matching = [reason for reason in raw_reasons if reason.lower() in group]
            return {
                "faulted": True,
                "error_code": "printer_fault",
                "reason_code": matching[0] if matching else code,
                "reason_label": label,
                "message": message,
                "raw_reasons": raw_reasons,
            }

    return {
        "faulted": True,
        "error_code": "printer_fault",
        "reason_code": raw_reasons[0] if raw_reasons else "unknown_printer_fault",
        "reason_label": "未知故障",
        "message": "打印机故障，请联系管理员处理",
        "raw_reasons": raw_reasons,
    }


def ready_state(printer_id: str = None, printer_name: str = None) -> dict[str, Any]:
    return {
        "available": True,
        "faulted": False,
        "error_code": None,
        "reason_code": "ready",
        "reason_label": "正常",
        "message": "打印机可用",
        "raw_reasons": [],
        "printer_id": printer_id,
        "printer_name": printer_name,
        "updated_at": time.time(),
    }


class PrinterFaultStateStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._state: dict[str, Any] = ready_state()

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def set_fault(
        self,
        printer_id: str = None,
        printer_name: str = None,
        raw_reasons: Optional[Iterable[Any]] = None,
    ) -> dict[str, Any]:
        mapped = map_ipp_fault_reasons(raw_reasons)
        state = {
            "available": False,
            "printer_id": printer_id,
            "printer_name": printer_name,
            "updated_at": time.time(),
            **mapped,
        }
        with self._lock:
            self._state = state
            return deepcopy(self._state)

    def clear(self, printer_id: str = None, printer_name: str = None) -> dict[str, Any]:
        state = ready_state(printer_id=printer_id, printer_name=printer_name)
        with self._lock:
            self._state = state
            return deepcopy(self._state)

    def _should_keep_fault_until_clean_probe(self, result: Any) -> bool:
        with self._lock:
            state = deepcopy(self._state)

        if not state.get("faulted"):
            return False

        current_reasons = _lower_reason_set(state.get("raw_reasons", []))
        reason_code = str(state.get("reason_code") or "").strip().lower()
        if reason_code:
            current_reasons.add(reason_code)

        probe_reasons = _lower_reason_set(getattr(result, "fault_reasons", []))
        probe_reasons |= _lower_reason_set(getattr(result, "printer_state_reasons", []))
        return any(
            _has_family_reason(current_reasons, family)
            and _still_reports_fault(probe_reasons, family)
            for family in STICKY_FAULT_REASON_FAMILIES
        )

    def update_from_probe(
        self,
        printer_id: str = None,
        printer_name: str = None,
        result: Any = None,
    ) -> dict[str, Any]:
        if result and getattr(result, "available", False) and getattr(result, "faulted", False):
            return self.set_fault(
                printer_id=printer_id,
                printer_name=printer_name,
                raw_reasons=getattr(result, "fault_reasons", []),
            )
        if result and getattr(result, "available", False):
            if self._should_keep_fault_until_clean_probe(result):
                return self.get_state()
            return self.clear(printer_id=printer_id, printer_name=printer_name)
        return self.get_state()
