from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .documents import DocumentPipeline
from .domain import ErrorCode, EventCallback, IppJobRef, PrintError, PrintEvent, PrintRequest, PrintState, USER_MESSAGES
from .ipp_device import active_job_fault, job_snapshot, printer_fault, printer_snapshot, probe_printer, validate_options
from .ipp_protocol import IppClient, IppResponseError, IppTransportError


STATE_MESSAGES = {
    PrintState.PREPARING: "正在准备打印文件……",
    PrintState.SUBMITTING: "正在发送到打印机……",
    PrintState.QUEUED: "打印机正在处理任务……",
    PrintState.PRINTING: "打印机正在打印……",
    PrintState.COMPLETED: "打印完成",
    PrintState.CANCELED: "打印任务已取消。",
    PrintState.UNCONFIRMED: USER_MESSAGES[ErrorCode.RESULT_UNCONFIRMED],
}

class DeviceJobRegistry:
    """Process-local serialization and duplicate-print protection per physical device."""

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._active: dict[str, str] = {}
        self._uncertain: dict[str, str] = {}

    def acquire(self, printer_uuid: str, job_id: str) -> threading.Lock | None:
        with self._guard:
            if printer_uuid in self._uncertain:
                return None
            lock = self._locks.setdefault(printer_uuid, threading.Lock())
        if not lock.acquire(blocking=False):
            return None
        with self._guard:
            self._active[printer_uuid] = job_id
        return lock

    def release(self, printer_uuid: str, lock: threading.Lock) -> None:
        with self._guard:
            self._active.pop(printer_uuid, None)
        lock.release()

    def mark_uncertain(self, printer_uuid: str, reason: str) -> None:
        with self._guard:
            self._uncertain[printer_uuid] = reason

    def clear_uncertain(self, printer_uuid: str) -> bool:
        with self._guard:
            return self._uncertain.pop(printer_uuid, None) is not None

    def is_uncertain(self, printer_uuid: str) -> bool:
        with self._guard:
            return printer_uuid in self._uncertain

    def active_count(self, printer_uuid: str) -> int:
        with self._guard:
            return 1 if printer_uuid in self._active else 0


DEVICE_JOBS = DeviceJobRegistry()


class IppPrintService:
    def __init__(self, documents: DocumentPipeline, logger=None, *, poll_seconds: float = 1.0, timeout_seconds: float = 900.0):
        self.documents = documents
        self.logger = logger or logging.getLogger(__name__)
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()

    def execute(self, request: PrintRequest, callback: Optional[EventCallback] = None) -> PrintEvent:
        execute_started_at = time.perf_counter()
        device_lock = DEVICE_JOBS.acquire(request.printer_uuid, request.job_id)
        if device_lock is None:
            return self._error_event(request, callback, PrintError(ErrorCode.PRINTER_BUSY, "device is active or locked after an unconfirmed job"))
        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[request.job_id] = cancel_event
        prepared = None
        try:
            self._emit(request, callback, PrintState.PREPARING)
            probe_started_at = time.perf_counter()
            try:
                probe = probe_printer(request.ipp_uri, timeout=5.0)
            except IppTransportError as exc:
                raise PrintError(ErrorCode.IPP_UNREACHABLE, str(exc)) from exc
            if not probe.compatible:
                raise PrintError(ErrorCode.IPP_CAPABILITY_MISSING, "; ".join(probe.issues))
            if probe.printer_uuid != request.printer_uuid:
                raise PrintError(ErrorCode.IPP_URI_INVALID, "configured URI now resolves to a different printer UUID")
            initial_fault = printer_fault(probe.snapshot)
            if initial_fault:
                raise PrintError(initial_fault, "blocking printer fault detected before submission", details={"printer_reasons": probe.snapshot.get("printer-state-reasons", [])})
            initial_state = int((probe.snapshot.get("printer-state") or [0])[0] or 0)
            if initial_state not in {3, 4}:
                raise PrintError(ErrorCode.PRINTER_USER_INTERVENTION, f"printer state {initial_state} cannot accept a new job")
            if not bool((probe.snapshot.get("printer-is-accepting-jobs") or [False])[0]):
                raise PrintError(ErrorCode.PRINTER_USER_INTERVENTION, "printer is not accepting jobs")

            probe_ms = (time.perf_counter() - probe_started_at) * 1000
            prepare_started_at = time.perf_counter()
            prepared = self.documents.prepare(request)
            prepare_ms = (time.perf_counter() - prepare_started_at) * 1000
            job_attributes = validate_options(probe.capabilities, request.options)
            client = IppClient(request.ipp_uri, timeout=30.0)
            self._emit(request, callback, PrintState.SUBMITTING)
            submit_started_at = time.perf_counter()
            try:
                response = client.print_pdf(prepared.print_pdf, request.unique_document_name, request.source_name, job_attributes)
            except IppTransportError as exc:
                raise PrintError(ErrorCode.IPP_SUBMISSION_UNCONFIRMED, str(exc), state=PrintState.UNCONFIRMED) from exc
            except IppResponseError as exc:
                raise PrintError(ErrorCode.IPP_SUBMISSION_FAILED, str(exc)) from exc
            device_job_id = int(response.first("job-id", 0) or 0)
            if device_job_id <= 0:
                raise PrintError(ErrorCode.IPP_SUBMISSION_UNCONFIRMED, "Print-Job response had no device job-id", state=PrintState.UNCONFIRMED)
            ref = IppJobRef(request.ipp_uri, request.printer_uuid, device_job_id, str(response.first("job-uri", "") or ""), request.unique_document_name)
            self.logger.info(
                "ipp_job_bound job_id=%s printer_uuid=%r device_job_id=%s job_uri=%r probe_ms=%.1f prepare_ms=%.1f submit_ms=%.1f pre_monitor_total_ms=%.1f",
                request.job_id,
                request.printer_uuid,
                ref.job_id,
                ref.job_uri,
                probe_ms,
                prepare_ms,
                (time.perf_counter() - submit_started_at) * 1000,
                (time.perf_counter() - execute_started_at) * 1000,
            )
            total_pages = prepared.page_count * request.options.copies
            self._emit(
                request,
                callback,
                PrintState.QUEUED,
                total_pages=total_pages,
                details={"ipp_job_id": ref.job_id},
            )
            return self._monitor(request, prepared.page_count, ref, client, cancel_event, callback)
        except PrintError as exc:
            if exc.state == PrintState.UNCONFIRMED:
                DEVICE_JOBS.mark_uncertain(request.printer_uuid, exc.code.value)
            return self._error_event(request, callback, exc)
        except Exception as exc:
            self.logger.exception("unexpected IPP print failure job_id=%s", request.job_id)
            return self._error_event(request, callback, PrintError(ErrorCode.SERVICE_NOT_READY, str(exc)))
        finally:
            if prepared:
                self.documents.cleanup(prepared)
            with self._cancel_lock:
                self._cancel_events.pop(request.job_id, None)
            DEVICE_JOBS.release(request.printer_uuid, device_lock)

    def _monitor(self, request, source_pages, ref, client, cancel_event, callback) -> PrintEvent:
        deadline = time.monotonic() + self.timeout_seconds
        total_pages = source_pages * request.options.copies
        detected_fault: ErrorCode | None = None
        cancel_sent = False
        last_signature = None
        while time.monotonic() < deadline:
            try:
                job = job_snapshot(client, ref.job_id)
                printer = printer_snapshot(client)
            except Exception as exc:
                raise PrintError(ErrorCode.IPP_JOB_QUERY_FAILED, str(exc), state=PrintState.UNCONFIRMED) from exc
            state = int((job.get("job-state") or [0])[0] or 0)
            current_page_raw = (job.get("job-impressions-completed") or [None])[0]
            current_page = min(total_pages, max(0, int(current_page_raw))) if current_page_raw is not None else None
            signature = (state, current_page, tuple(job.get("job-state-reasons", [])), tuple(printer.get("printer-state-reasons", [])))
            if signature != last_signature:
                self.logger.info(
                    "ipp_job_status job_id=%s device_job_id=%s state=%s pages=%s/%s job_reasons=%r printer_reasons=%r",
                    request.job_id,
                    ref.job_id,
                    state,
                    current_page,
                    total_pages,
                    job.get("job-state-reasons", []),
                    printer.get("printer-state-reasons", []),
                )
                last_signature = signature

            if state == 9:
                event = PrintEvent(
                    PrintState.COMPLETED,
                    STATE_MESSAGES[PrintState.COMPLETED],
                    request.job_id,
                    current_page=total_pages,
                    total_pages=total_pages,
                    details={"ipp_job_id": ref.job_id, "completion_basis": "ipp_job_completed"},
                )
                if callback:
                    callback(event)
                return event
            if state == 8:
                raise PrintError(ErrorCode.IPP_JOB_ABORTED, "device aborted the IPP job", details={"job_reasons": job.get("job-state-reasons", [])})
            if state == 7:
                if detected_fault:
                    raise PrintError(detected_fault, "faulted IPP job was canceled", details={"job_reasons": job.get("job-state-reasons", [])})
                event = PrintEvent(
                    PrintState.CANCELED,
                    STATE_MESSAGES[PrintState.CANCELED],
                    request.job_id,
                    current_page=current_page,
                    total_pages=total_pages,
                    error_code=ErrorCode.PRINT_CANCELED,
                )
                if callback:
                    callback(event)
                return event

            if cancel_event.is_set() and not cancel_sent:
                self._send_cancel(client, ref.job_id)
                cancel_sent = True
            fault = active_job_fault(job, printer)
            if fault and not cancel_sent:
                detected_fault = fault
                self.logger.warning("ipp_active_job_fault job_id=%s device_job_id=%s code=%s", request.job_id, ref.job_id, fault.value)
                self._send_cancel(client, ref.job_id)
                cancel_sent = True

            event_state = PrintState.PRINTING if state == 5 else PrintState.QUEUED
            self._emit(
                request,
                callback,
                event_state,
                current_page=current_page,
                total_pages=total_pages,
                details={"ipp_job_id": ref.job_id, "ipp_job_state": state},
            )
            time.sleep(self.poll_seconds)

        try:
            self._send_cancel(client, ref.job_id)
            terminal = self._wait_for_cancel(client, ref.job_id, 15.0)
        except Exception as exc:
            raise PrintError(ErrorCode.IPP_CANCEL_FAILED, str(exc), state=PrintState.UNCONFIRMED) from exc
        if terminal != 7:
            raise PrintError(ErrorCode.IPP_CANCEL_FAILED, f"timeout cancellation ended in state {terminal}", state=PrintState.UNCONFIRMED)
        raise PrintError(ErrorCode.PRINT_TIMEOUT, f"IPP job exceeded {self.timeout_seconds:.0f}s")

    @staticmethod
    def _send_cancel(client: IppClient, job_id: int) -> None:
        try:
            client.cancel_job(job_id)
        except Exception as exc:
            raise PrintError(ErrorCode.IPP_CANCEL_FAILED, str(exc), state=PrintState.UNCONFIRMED) from exc

    def _wait_for_cancel(self, client: IppClient, job_id: int, timeout: float) -> int:
        deadline = time.monotonic() + timeout
        state = 0
        while time.monotonic() < deadline:
            state = int((job_snapshot(client, job_id).get("job-state") or [0])[0] or 0)
            if state in {7, 8, 9}:
                return state
            time.sleep(self.poll_seconds)
        return state

    def cancel(self, job_id: str) -> bool:
        with self._cancel_lock:
            event = self._cancel_events.get(job_id)
        if not event:
            return False
        event.set()
        return True

    def _error_event(self, request: PrintRequest, callback: Optional[EventCallback], exc: PrintError) -> PrintEvent:
        self.logger.error("ipp_print_failed job_id=%s code=%s state=%s reason=%s details=%r", request.job_id, exc.code.value, exc.state.value, exc.technical_message, exc.details)
        event = PrintEvent(exc.state, exc.user_message, request.job_id, error_code=exc.code, details=exc.details)
        if callback:
            callback(event)
        return event

    @staticmethod
    def _emit(
        request,
        callback,
        state,
        message=None,
        current_page=None,
        total_pages=None,
        details=None,
    ) -> PrintEvent:
        event = PrintEvent(
            state,
            message or STATE_MESSAGES[state],
            request.job_id,
            current_page=current_page,
            total_pages=total_pages,
            details=details or {},
        )
        if callback:
            callback(event)
        return event
