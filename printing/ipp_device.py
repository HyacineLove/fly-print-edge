from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .domain import ErrorCode, PrintError, PrintOptions
from .ipp_protocol import (
    IppClient,
    IppResponse,
    OP_CANCEL_JOB,
    OP_GET_JOB_ATTRIBUTES,
    OP_PRINT_JOB,
    TAG_INTEGER,
    TAG_KEYWORD,
)


REQUIRED_OPERATIONS = {OP_PRINT_JOB, OP_CANCEL_JOB, OP_GET_JOB_ATTRIBUTES}
PRINTER_ATTRIBUTES = [
    "printer-uuid", "printer-name", "printer-info", "printer-make-and-model",
    "printer-uri-supported", "printer-state", "printer-state-reasons", "printer-state-message",
    "printer-is-accepting-jobs", "operations-supported",
    "document-format-supported", "ipp-versions-supported", "job-creation-attributes-supported",
    "copies-supported", "sides-supported", "print-color-mode-supported", "media-supported",
    "printer-resolution-supported", "printer-alert", "printer-alert-description",
    "marker-names", "marker-levels", "marker-high-levels", "marker-low-levels",
]
JOB_ATTRIBUTES = [
    "job-id", "job-uri", "job-name", "job-state", "job-state-reasons", "job-state-message",
    "job-impressions", "job-impressions-completed",
    "copies", "copies-actual", "sides", "sides-actual", "print-color-mode",
    "print-color-mode-actual", "media", "media-actual", "time-at-creation",
    "time-at-processing", "time-at-completed",
]

FAULT_TOKENS = {
    "media-empty": ErrorCode.PRINTER_OUT_OF_PAPER,
    "media-needed": ErrorCode.PRINTER_OUT_OF_PAPER,
    "input-tray-missing": ErrorCode.PRINTER_OUT_OF_PAPER,
    "media-jam": ErrorCode.PRINTER_JAMMED,
    "toner-empty": ErrorCode.PRINTER_OUT_OF_TONER,
    "marker-supply-empty": ErrorCode.PRINTER_OUT_OF_TONER,
    "door-open": ErrorCode.PRINTER_COVER_OPEN,
    "cover-open": ErrorCode.PRINTER_COVER_OPEN,
    "offline": ErrorCode.PRINTER_OFFLINE,
    "shutdown": ErrorCode.PRINTER_OFFLINE,
    "service-requested": ErrorCode.PRINTER_USER_INTERVENTION,
}
PRINTER_STATUS_MESSAGES = {
    "idle": "打印机可用。",
    "printing": "打印机正在处理其他任务，请稍候。",
    "printer_out_of_paper": "打印机缺纸，请联系工作人员补纸。",
    "printer_out_of_toner": "打印机碳粉已用尽，请联系工作人员处理。",
    "printer_jammed": "打印机发生卡纸，请联系工作人员处理。",
    "printer_cover_open": "打印机机盖未关闭，请联系工作人员处理。",
    "printer_offline": "打印机连接已断开，请联系工作人员。",
    "printer_user_intervention": "打印机需要处理，请联系工作人员。",
    "printer_other_fault": "打印机报告了需要处理的设备故障。",
    "printer_unconfirmed_lock": "无法确认上次打印结果，请联系工作人员核对。",
    "printer_stopped": "打印机已停止，请检查设备面板。",
    "printer_state_unknown": "暂时无法确认打印机状态。",
    "printer_not_accepting_jobs": "打印机当前拒绝接收新任务。",
    "ipp_unreachable": "无法连接打印机，请检查设备电源和网络。",
}


def response_values(response: IppResponse, names: list[str]) -> dict[str, list[Any]]:
    return {name: response.values(name) for name in names if response.values(name)}


def _clean(values: list[Any]) -> list[str]:
    return [str(value).strip().lower() for value in values if str(value).strip().lower() not in {"", "none"}]


def _reason_base(reason: str) -> str:
    for suffix in ("-error", "-warning", "-report"):
        if reason.endswith(suffix):
            return reason[:-len(suffix)]
    return reason


def map_reason_fault(reasons: list[str]) -> ErrorCode | None:
    for reason in reasons:
        base = _reason_base(reason)
        for token, code in FAULT_TOKENS.items():
            if base == token or base.startswith(token + "-"):
                return code
    return None


def printer_fault(snapshot: dict[str, Any]) -> ErrorCode | None:
    """Return only a current, blocking printer fault."""
    reasons = _clean(snapshot.get("printer-state-reasons", []))
    error_reasons = [reason for reason in reasons if reason.endswith("-error")]
    return map_reason_fault(error_reasons)


def active_job_fault(job: dict[str, Any], printer: dict[str, Any]) -> ErrorCode | None:
    job_state = int((job.get("job-state") or [0])[0] or 0)
    job_reasons = _clean(job.get("job-state-reasons", []))
    job_fault = map_reason_fault(
        job_reasons if job_state == 6 else [reason for reason in job_reasons if reason.endswith("-error")]
    )
    if job_fault:
        return job_fault
    printer_error = printer_fault(printer)
    if printer_error:
        return printer_error
    return ErrorCode.PRINTER_USER_INTERVENTION if job_state == 6 else None


@dataclass(frozen=True)
class PrinterObservation:
    snapshot: dict[str, Any]
    uncertain: bool = False
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PrinterRuntimeState:
    printer_status: str
    observed_at: datetime

    def public_dict(self) -> dict[str, Any]:
        return {
            "printer_status": self.printer_status,
            "source_observed_at": self.observed_at.isoformat(),
        }


def normalize_printer_runtime(observation: PrinterObservation) -> PrinterRuntimeState:
    """Translate one IPP sample into the only Cloud/UI-facing printer status."""
    snapshot = observation.snapshot
    state = int((snapshot.get("printer-state") or [0])[0] or 0)
    accepting = bool((snapshot.get("printer-is-accepting-jobs") or [False])[0])
    reasons = _clean(snapshot.get("printer-state-reasons", []))
    fault = printer_fault(snapshot)
    if fault:
        return PrinterRuntimeState(fault.value, observation.observed_at)

    unknown_errors = [reason for reason in reasons if reason.endswith("-error")]
    if unknown_errors:
        return PrinterRuntimeState("printer_other_fault", observation.observed_at)

    if observation.uncertain:
        return PrinterRuntimeState("printer_unconfirmed_lock", observation.observed_at)

    if state == 5:
        return PrinterRuntimeState("printer_stopped", observation.observed_at)
    if state not in {3, 4}:
        return PrinterRuntimeState("printer_state_unknown", observation.observed_at)

    if state == 4:
        return PrinterRuntimeState("printing", observation.observed_at)

    if not accepting:
        return PrinterRuntimeState("printer_not_accepting_jobs", observation.observed_at)
    return PrinterRuntimeState("idle", observation.observed_at)


def printer_status_text(runtime: PrinterRuntimeState) -> str:
    return runtime.printer_status


def printer_status_message(status: str) -> str:
    return PRINTER_STATUS_MESSAGES.get(status, "当前打印机暂不可用，请联系工作人员。")


@dataclass(frozen=True)
class IppPrinterProbe:
    compatible: bool
    issues: tuple[str, ...]
    name: str
    make_model: str
    printer_uuid: str
    ipp_uri: str
    capabilities: dict[str, Any]
    snapshot: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "ipp",
            "make_model": self.make_model,
            "printer_uuid": self.printer_uuid,
            "ipp_uri": self.ipp_uri,
            "compatible": self.compatible,
            "issues": list(self.issues),
            "status": printer_status_text(normalize_printer_runtime(PrinterObservation(self.snapshot))),
            "capabilities": self.capabilities,
            "duplex_supported": self.capabilities.get("duplex_supported"),
            "color_supported": self.capabilities.get("color_supported"),
            "capability_summary": self.capabilities.get("capability_summary"),
        }


def normalize_capabilities(snapshot: dict[str, Any]) -> dict[str, Any]:
    sides = [str(value) for value in snapshot.get("sides-supported", [])]
    colors = [str(value) for value in snapshot.get("print-color-mode-supported", [])]
    media = [str(value) for value in snapshot.get("media-supported", [])]
    copy_range = snapshot.get("copies-supported", [[1, 1]])
    minimum, maximum = 1, 1
    if copy_range and isinstance(copy_range[0], list) and len(copy_range[0]) == 2:
        minimum, maximum = int(copy_range[0][0]), int(copy_range[0][1])
    duplex = any(value.startswith("two-sided-") for value in sides)
    color = "color" in colors
    return {
        "document_formats": [str(value) for value in snapshot.get("document-format-supported", [])],
        "ipp_versions": [str(value) for value in snapshot.get("ipp-versions-supported", [])],
        "operations": [int(value) for value in snapshot.get("operations-supported", [])],
        "job_creation_attributes": [str(value) for value in snapshot.get("job-creation-attributes-supported", [])],
        "copies": {"min": minimum, "max": maximum},
        "copies_supported": [[minimum, maximum]],
        "sides": sides,
        "duplex": ["simplex"] + (["longedge", "shortedge"] if duplex else []),
        "duplex_supported": duplex,
        "color_modes": colors,
        "color_model": (["mono", "color"] if color else ["mono"]),
        "color_supported": color,
        "media": media,
        "page_size": media,
        "resolution": [str(value) for value in snapshot.get("printer-resolution-supported", [])],
        "capability_summary": f"单双面: {'支持' if duplex else '不支持'}, 彩色: {'支持' if color else '不支持'}",
    }


def probe_printer(ipp_uri: str, *, timeout: float = 5.0) -> IppPrinterProbe:
    client = IppClient(ipp_uri, timeout=timeout)
    response = client.get_printer_attributes(PRINTER_ATTRIBUTES)
    snapshot = response_values(response, PRINTER_ATTRIBUTES)
    capabilities = normalize_capabilities(snapshot)
    issues: list[str] = []
    versions = set(capabilities["ipp_versions"])
    operations = set(capabilities["operations"])
    formats = set(capabilities["document_formats"])
    creation = set(capabilities["job_creation_attributes"])
    printer_uuid = str((snapshot.get("printer-uuid") or [""])[0]).strip()
    if "2.0" not in versions:
        issues.append("设备未声明支持 IPP 2.0")
    if "application/pdf" not in formats:
        issues.append("设备不支持直接打印 PDF")
    if missing := REQUIRED_OPERATIONS - operations:
        issues.append("设备缺少必要的 IPP 作业操作: " + ", ".join(f"0x{item:04X}" for item in sorted(missing)))
    for required in ("copies", "sides", "print-color-mode", "media", "ipp-attribute-fidelity"):
        if required not in creation:
            issues.append(f"设备不支持作业属性 {required}")
    if not snapshot.get("copies-supported"):
        issues.append("device did not report copies-supported")
    if not capabilities.get("sides"):
        issues.append("device did not report sides-supported")
    if not capabilities.get("color_modes"):
        issues.append("device did not report print-color-mode-supported")
    if not capabilities.get("media"):
        issues.append("device did not report media-supported")
    if not printer_uuid:
        issues.append("设备未返回稳定的 printer-uuid")
    return IppPrinterProbe(
        compatible=not issues,
        issues=tuple(issues),
        name=str((snapshot.get("printer-name") or snapshot.get("printer-info") or ["IPP Printer"])[0]),
        make_model=str((snapshot.get("printer-make-and-model") or [""])[0]),
        printer_uuid=printer_uuid,
        ipp_uri=client.printer_uri,
        capabilities=capabilities,
        snapshot=snapshot,
    )


def printer_snapshot(client: IppClient) -> dict[str, Any]:
    return response_values(client.get_printer_attributes(PRINTER_ATTRIBUTES), PRINTER_ATTRIBUTES)


def job_snapshot(client: IppClient, job_id: int) -> dict[str, Any]:
    return response_values(client.get_job_attributes(job_id, JOB_ATTRIBUTES), JOB_ATTRIBUTES)


def validate_options(capabilities: dict[str, Any], options: PrintOptions) -> list[tuple[int, str, Any]]:
    supported_copies = capabilities.get("copies") or {"min": 1, "max": 1}
    if not int(supported_copies.get("min", 1)) <= options.copies <= int(supported_copies.get("max", 1)):
        raise PrintError(ErrorCode.IPP_PARAMETER_UNSUPPORTED, f"copies={options.copies} is unsupported")
    if options.ipp_sides not in capabilities.get("sides", []):
        raise PrintError(ErrorCode.IPP_PARAMETER_UNSUPPORTED, f"sides={options.ipp_sides} is unsupported")
    if options.ipp_color_mode not in capabilities.get("color_modes", []):
        raise PrintError(ErrorCode.IPP_PARAMETER_UNSUPPORTED, f"color={options.ipp_color_mode} is unsupported")
    if not options.ipp_media or options.ipp_media not in capabilities.get("media", []):
        raise PrintError(ErrorCode.IPP_PARAMETER_UNSUPPORTED, f"media={options.ipp_media or options.paper_size} is unsupported")
    return [
        (TAG_INTEGER, "copies", options.copies),
        (TAG_KEYWORD, "sides", options.ipp_sides),
        (TAG_KEYWORD, "print-color-mode", options.ipp_color_mode),
        (TAG_KEYWORD, "media", options.ipp_media),
    ]
