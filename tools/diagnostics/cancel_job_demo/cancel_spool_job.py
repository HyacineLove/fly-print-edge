"""Diagnose whether a Windows print job can be cancelled while the printer is faulty.

Run examples:
  venv\\Scripts\\python.exe tools\\diagnostics\\cancel_job_demo\\cancel_spool_job.py --list
  venv\\Scripts\\python.exe tools\\diagnostics\\cancel_job_demo\\cancel_spool_job.py --printer "HPIA24DD9 (HP Color LaserJet Pro 3288)" --list-jobs
  venv\\Scripts\\python.exe tools\\diagnostics\\cancel_job_demo\\cancel_spool_job.py --printer "HPIA24DD9 (HP Color LaserJet Pro 3288)" --job-id 2 --cancel
  venv\\Scripts\\python.exe tools\\diagnostics\\cancel_job_demo\\cancel_spool_job.py --printer "HPIA24DD9 (HP Color LaserJet Pro 3288)" --submit-raw --cancel-after 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from typing import Any

try:
    import win32con
    import win32print
    import win32timezone  # noqa: F401 - required by pywin32 when deserializing job times.
except ImportError as exc:
    print(f"cancel_demo import_error missing_module={exc.name!r} error={exc}", file=sys.stderr)
    raise SystemExit(2)


PRINTER_ENUM_FLAGS = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS


def log(label: str, **fields: Any) -> None:
    timestamp = dt.datetime.now().isoformat(timespec="seconds")
    rendered = " ".join(f"{key}={value!r}" for key, value in fields.items())
    print(f"{timestamp} cancel_demo {label} {rendered}".rstrip(), flush=True)


def enum_printers() -> list[dict[str, Any]]:
    printers = []
    for item in win32print.EnumPrinters(PRINTER_ENUM_FLAGS, None, 2):
        printers.append(
            {
                "name": item.get("pPrinterName") or item.get("Name"),
                "driver": item.get("pDriverName") or item.get("DriverName"),
                "port": item.get("pPortName") or item.get("PortName"),
                "status": item.get("Status"),
            }
        )
    return [printer for printer in printers if printer["name"]]


def resolve_printer(name: str) -> dict[str, Any]:
    printers = enum_printers()
    exact = [printer for printer in printers if printer["name"] == name]
    casefold = [printer for printer in printers if printer["name"].casefold() == name.casefold()]
    matches = exact or casefold

    if len(matches) == 1:
        printer = matches[0]
        log(
            "printer_resolved",
            requested=name,
            resolved=printer["name"],
            driver=printer["driver"],
            port=printer["port"],
            status=printer["status"],
        )
        return printer

    log(
        "printer_resolve_failed",
        requested=name,
        match_count=len(matches),
        available=[printer["name"] for printer in printers],
    )
    raise SystemExit(1)


def open_printer(printer_name: str):
    return win32print.OpenPrinter(
        printer_name,
        {"DesiredAccess": win32print.PRINTER_ALL_ACCESS},
    )


def enum_jobs(printer_name: str) -> list[dict[str, Any]]:
    handle = open_printer(printer_name)
    try:
        return win32print.EnumJobs(handle, 0, 999, 1)
    finally:
        win32print.ClosePrinter(handle)


def summarize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("JobId"),
        "document": job.get("pDocument"),
        "status": job.get("Status"),
        "status_text": job.get("pStatus"),
        "user": job.get("pUserName"),
        "pages_printed": job.get("PagesPrinted"),
        "total_pages": job.get("TotalPages"),
    }


def list_jobs(printer_name: str) -> list[dict[str, Any]]:
    jobs = enum_jobs(printer_name)
    if not jobs:
        log("jobs_empty", printer=printer_name)
        return []

    for job in jobs:
        log("job_seen", printer=printer_name, **summarize_job(job))
    return jobs


def submit_raw_job(printer_name: str) -> int:
    handle = open_printer(printer_name)
    document_name = "FlyPrint cancel diagnostic RAW job"
    payload = (
        "FlyPrint cancel diagnostic page\r\n"
        f"Created at: {dt.datetime.now().isoformat(timespec='seconds')}\r\n"
        "This job is safe to cancel while testing printer fault handling.\r\n"
        "\f"
    ).encode("ascii")

    try:
        job_id = win32print.StartDocPrinter(
            handle,
            1,
            (document_name, None, "RAW"),
        )
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, payload)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)

    log("raw_job_submitted", printer=printer_name, job_id=job_id, document=document_name)
    return int(job_id)


def cancel_job(printer_name: str, job_id: int) -> None:
    jobs = enum_jobs(printer_name)
    matching_jobs = [job for job in jobs if int(job.get("JobId", -1)) == job_id]
    if not matching_jobs:
        log(
            "target_job_missing_before_cancel",
            printer=printer_name,
            job_id=job_id,
            visible_job_ids=[job.get("JobId") for job in jobs],
        )
        raise SystemExit(1)

    log("target_job_before_cancel", printer=printer_name, **summarize_job(matching_jobs[0]))

    handle = open_printer(printer_name)
    try:
        win32print.SetJob(handle, job_id, 0, None, win32print.JOB_CONTROL_DELETE)
    except Exception as exc:
        log("cancel_request_failed", printer=printer_name, job_id=job_id, error=str(exc))
        raise
    finally:
        win32print.ClosePrinter(handle)

    log("cancel_requested", printer=printer_name, job_id=job_id)


def wait_until_job_removed(printer_name: str, job_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        jobs = enum_jobs(printer_name)
        matching_jobs = [job for job in jobs if int(job.get("JobId", -1)) == job_id]
        if not matching_jobs:
            log("cancel_confirmed", printer=printer_name, job_id=job_id, attempt=attempt)
            return True

        log(
            "cancel_pending",
            printer=printer_name,
            job_id=job_id,
            attempt=attempt,
            job=summarize_job(matching_jobs[0]),
        )
        time.sleep(0.5)

    log("cancel_confirm_timeout", printer=printer_name, job_id=job_id, timeout=timeout)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit/list/cancel Windows spooler jobs for printer fault diagnostics."
    )
    parser.add_argument("--printer", help="Exact Windows printer queue name.")
    parser.add_argument("--list", action="store_true", help="List available printer queues.")
    parser.add_argument("--list-jobs", action="store_true", help="List jobs for --printer.")
    parser.add_argument("--job-id", type=int, help="Existing Windows spooler JobId to cancel.")
    parser.add_argument("--cancel", action="store_true", help="Cancel --job-id.")
    parser.add_argument(
        "--submit-raw",
        action="store_true",
        help="Submit a small RAW test job and print the returned JobId.",
    )
    parser.add_argument(
        "--cancel-after",
        type=float,
        default=None,
        help="Seconds to wait after --submit-raw before cancelling that submitted job.",
    )
    parser.add_argument(
        "--confirm-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for cancelled job to disappear from EnumJobs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list:
        for printer in enum_printers():
            log("printer_seen", **printer)
        return 0

    if not args.printer:
        log("usage_error", message="--printer is required unless --list is used")
        return 2

    printer = resolve_printer(args.printer)
    printer_name = printer["name"]

    if args.list_jobs:
        list_jobs(printer_name)

    submitted_job_id = None
    if args.submit_raw:
        submitted_job_id = submit_raw_job(printer_name)

    target_job_id = args.job_id or submitted_job_id
    if args.cancel_after is not None:
        if target_job_id is None:
            log("usage_error", message="--cancel-after requires --submit-raw or --job-id")
            return 2
        log("waiting_before_cancel", printer=printer_name, job_id=target_job_id, seconds=args.cancel_after)
        time.sleep(args.cancel_after)
        args.cancel = True

    if args.cancel:
        if target_job_id is None:
            log("usage_error", message="--cancel requires --job-id or --submit-raw")
            return 2
        cancel_job(printer_name, target_job_id)
        return 0 if wait_until_job_removed(printer_name, target_job_id, args.confirm_timeout) else 1

    if not args.list_jobs and not args.submit_raw:
        list_jobs(printer_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
