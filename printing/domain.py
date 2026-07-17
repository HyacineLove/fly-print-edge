from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from print_options import normalize_print_options


class PrintState(str, Enum):
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    QUEUED = "queued"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    UNCONFIRMED = "unconfirmed"


TERMINAL_STATES = {PrintState.COMPLETED, PrintState.FAILED, PrintState.CANCELED, PrintState.UNCONFIRMED}


class ErrorCode(str, Enum):
    SERVICE_NOT_READY = "service_not_ready"
    CONFIG_INCOMPLETE = "config_incomplete"
    SOURCE_NOT_FOUND = "source_not_found"
    DOCUMENT_UNSUPPORTED = "document_unsupported"
    DOCUMENT_CONVERSION_FAILED = "document_conversion_failed"
    DOCUMENT_PREPARATION_FAILED = "document_preparation_failed"
    IPP_URI_INVALID = "ipp_uri_invalid"
    IPP_UNREACHABLE = "ipp_unreachable"
    IPP_CAPABILITY_MISSING = "ipp_capability_missing"
    IPP_PARAMETER_UNSUPPORTED = "ipp_parameter_unsupported"
    IPP_SUBMISSION_FAILED = "ipp_submission_failed"
    IPP_SUBMISSION_UNCONFIRMED = "ipp_submission_unconfirmed"
    IPP_JOB_QUERY_FAILED = "ipp_job_query_failed"
    IPP_JOB_ABORTED = "ipp_job_aborted"
    IPP_CANCEL_FAILED = "ipp_cancel_failed"
    PRINTER_BUSY = "printer_busy"
    PRINTER_REJECTED_DOCUMENT = "printer_rejected_document"
    PRINTER_OUT_OF_PAPER = "printer_out_of_paper"
    PRINTER_OUT_OF_TONER = "printer_out_of_toner"
    PRINTER_JAMMED = "printer_jammed"
    PRINTER_COVER_OPEN = "printer_cover_open"
    PRINTER_OFFLINE = "printer_offline"
    PRINTER_USER_INTERVENTION = "printer_user_intervention"
    PRINT_CANCELED = "print_canceled"
    PRINT_TIMEOUT = "print_timeout"
    RESULT_UNCONFIRMED = "result_unconfirmed"


_DOCUMENT_MESSAGE = "文档处理失败，请重新上传；如仍然失败，请联系工作人员。"
_UNCONFIRMED_MESSAGE = "无法确认本次打印结果，请勿重复提交，请联系工作人员。"

USER_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.SERVICE_NOT_READY: "打印服务暂不可用，请联系工作人员。",
    ErrorCode.CONFIG_INCOMPLETE: "打印服务尚未配置完成，请联系工作人员。",
    ErrorCode.SOURCE_NOT_FOUND: _DOCUMENT_MESSAGE,
    ErrorCode.DOCUMENT_UNSUPPORTED: _DOCUMENT_MESSAGE,
    ErrorCode.DOCUMENT_CONVERSION_FAILED: _DOCUMENT_MESSAGE,
    ErrorCode.DOCUMENT_PREPARATION_FAILED: _DOCUMENT_MESSAGE,
    ErrorCode.IPP_URI_INVALID: "当前打印机配置无效，请联系工作人员。",
    ErrorCode.IPP_UNREACHABLE: "打印机连接已断开，请联系工作人员。",
    ErrorCode.IPP_CAPABILITY_MISSING: "当前打印机不受支持，请联系工作人员。",
    ErrorCode.IPP_PARAMETER_UNSUPPORTED: "当前打印机不支持所选参数，请联系工作人员。",
    ErrorCode.IPP_SUBMISSION_FAILED: "打印任务发送失败，请联系工作人员。",
    ErrorCode.IPP_SUBMISSION_UNCONFIRMED: _UNCONFIRMED_MESSAGE,
    ErrorCode.IPP_JOB_QUERY_FAILED: _UNCONFIRMED_MESSAGE,
    ErrorCode.IPP_JOB_ABORTED: "打印机无法处理该文档，请联系工作人员。",
    ErrorCode.IPP_CANCEL_FAILED: _UNCONFIRMED_MESSAGE,
    ErrorCode.PRINTER_BUSY: "打印机正在处理其他任务，请稍后再试。",
    ErrorCode.PRINTER_REJECTED_DOCUMENT: "打印机无法处理该文档，请联系工作人员。",
    ErrorCode.PRINTER_OUT_OF_PAPER: "打印机缺纸，请联系工作人员补纸。",
    ErrorCode.PRINTER_OUT_OF_TONER: "打印机碳粉已用尽，请联系工作人员处理。",
    ErrorCode.PRINTER_JAMMED: "打印机发生卡纸，请联系工作人员处理。",
    ErrorCode.PRINTER_COVER_OPEN: "打印机机盖未关闭，请联系工作人员处理。",
    ErrorCode.PRINTER_OFFLINE: "打印机连接已断开，请联系工作人员。",
    ErrorCode.PRINTER_USER_INTERVENTION: "打印机需要处理，请联系工作人员。",
    ErrorCode.PRINT_CANCELED: "打印任务已取消。",
    ErrorCode.PRINT_TIMEOUT: _UNCONFIRMED_MESSAGE,
    ErrorCode.RESULT_UNCONFIRMED: _UNCONFIRMED_MESSAGE,
}

ADMIN_ACTIONS: dict[ErrorCode, str] = {
    ErrorCode.IPP_URI_INVALID: "请在打印机管理中重新检测完整的 IPP URI。",
    ErrorCode.IPP_UNREACHABLE: "请检查网线、打印机电源和 IPP 地址。",
    ErrorCode.IPP_CAPABILITY_MISSING: "请确认设备支持 IPP 2.0、PDF、任务查询与取消。",
    ErrorCode.IPP_PARAMETER_UNSUPPORTED: "请检查设备能力与任务参数。",
    ErrorCode.DOCUMENT_CONVERSION_FAILED: "请检查 LibreOffice 路径并执行 DOCX 转换测试。",
}


MEDIA_BY_PAPER = {
    "A3": "iso_a3_297x420mm",
    "A4": "iso_a4_210x297mm",
    "A5": "iso_a5_148x210mm",
    "B5": "iso_b5_176x250mm",
    "Letter": "na_letter_8.5x11in",
    "Legal": "na_legal_8.5x14in",
    "Tabloid": "na_ledger_11x17in",
}


@dataclass(frozen=True)
class PrintOptions:
    copies: int = 1
    duplex: str = "simplex"
    color_mode: str = "mono"
    paper_size: str = "A4"
    scale_mode: str = "fit"
    max_upscale: float = 3.0

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "PrintOptions":
        raw = normalize_print_options(dict(value or {}))
        try:
            copies = max(1, int(raw.get("copies", 1)))
        except (TypeError, ValueError):
            copies = 1
        duplex = str(raw.get("duplex") or "simplex")
        if duplex not in {"simplex", "longedge", "shortedge"}:
            duplex = "simplex"
        color = str(raw.get("color_mode") or "mono")
        if color not in {"mono", "color"}:
            color = "mono"
        scale = str(raw.get("scale_mode") or "fit").lower()
        if scale not in {"fit", "actual", "fill"}:
            scale = "fit"
        try:
            max_upscale = max(0.01, float(raw.get("max_upscale", 3.0)))
        except (TypeError, ValueError):
            max_upscale = 3.0
        return cls(copies, duplex, color, str(raw.get("paper_size") or raw.get("page_size") or "A4"), scale, max_upscale)

    @property
    def ipp_sides(self) -> str:
        return {"simplex": "one-sided", "longedge": "two-sided-long-edge", "shortedge": "two-sided-short-edge"}[self.duplex]

    @property
    def ipp_color_mode(self) -> str:
        return "color" if self.color_mode == "color" else "monochrome"

    @property
    def ipp_media(self) -> str:
        return MEDIA_BY_PAPER.get(self.paper_size, "")


@dataclass(frozen=True)
class PrintRequest:
    job_id: str
    printer_name: str
    printer_uuid: str
    ipp_uri: str
    source_path: Path
    source_name: str
    options: PrintOptions = field(default_factory=PrintOptions)
    printer_id: Optional[str] = None
    content_hash: Optional[str] = None

    @property
    def unique_document_name(self) -> str:
        safe = "".join(ch for ch in self.job_id if ch.isalnum() or ch in "-_")[:64]
        return f"FlyPrint-{safe or 'job'}"


@dataclass(frozen=True)
class PreparedDocument:
    source_pdf: Path
    print_pdf: Path
    page_count: int
    cache_hit: bool = False


@dataclass(frozen=True)
class IppJobRef:
    printer_uri: str
    printer_uuid: str
    job_id: int
    job_uri: str
    job_name: str


@dataclass(frozen=True)
class PrintEvent:
    state: PrintState
    message: str
    job_id: str
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    error_code: Optional[ErrorCode] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["error_code"] = self.error_code.value if self.error_code else None
        data.pop("details", None)
        return data


EventCallback = Callable[[PrintEvent], None]


class PrintError(RuntimeError):
    def __init__(self, code: ErrorCode, technical_message: str, *, state: PrintState = PrintState.FAILED, details: Optional[Mapping[str, Any]] = None):
        super().__init__(technical_message)
        self.code = code
        self.technical_message = technical_message
        self.state = state
        self.details = dict(details or {})

    @property
    def user_message(self) -> str:
        return USER_MESSAGES[self.code]

    @property
    def admin_action(self) -> str:
        return ADMIN_ACTIONS.get(self.code, "请复制诊断摘要并查看运维文档。")
