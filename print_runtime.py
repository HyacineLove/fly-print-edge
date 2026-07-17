from __future__ import annotations

from pathlib import Path

from portable_temp import get_portable_temp_dir
from printing.documents import DocumentPreparer
from printing.domain import PrintOptions, PrintRequest
from printing.service import IppPrintService


def build_print_service(config_repo, logger) -> IppPrintService:
    settings = config_repo.get_full_config().get("settings", {})
    root = Path(get_portable_temp_dir()) / "ipp-printing"
    return IppPrintService(
        DocumentPreparer(str(settings.get("libreoffice_path") or ""), root / "document-cache", root / "jobs", logger),
        logger,
    )


def build_print_request(config_repo, *, job_id, printer_id, printer_name, file_path, source_name, print_options, content_hash=None) -> PrintRequest:
    printer = config_repo.get_printer_by_id(printer_id) if printer_id else None
    if not printer:
        printer = config_repo.get_printer_by_name(printer_name)
    if not printer:
        raise ValueError(f"managed printer not found: {printer_name!r}")
    return PrintRequest(
        job_id=str(job_id),
        printer_id=str(printer.get("id") or printer_id or "") or None,
        printer_name=str(printer.get("name") or printer_name),
        printer_uuid=str(printer.get("printer_uuid") or ""),
        ipp_uri=str(printer.get("ipp_uri") or ""),
        source_path=Path(file_path),
        source_name=source_name or Path(file_path).name,
        options=PrintOptions.from_mapping(print_options),
        content_hash=content_hash,
    )
