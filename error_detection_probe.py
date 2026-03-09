import argparse
import json
import os
import platform
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from printer_utils import PrinterManager


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def match_categories(status_text: str) -> Dict[str, bool]:
    text = normalize_text(status_text)
    paper_keywords = ["缺纸", "paper", "out of paper", "no paper"]
    jam_keywords = ["卡纸", "jam", "paper jam"]
    ink_keywords = ["缺墨", "ink", "toner", "cartridge", "墨盒", "碳粉"]
    return {
        "paper_out": any(k in text for k in paper_keywords),
        "paper_jam": any(k in text for k in jam_keywords),
        "ink_shortage": any(k in text for k in ink_keywords),
    }


def merge_matches(base: Dict[str, bool], extra: Dict[str, bool]) -> Dict[str, bool]:
    return {
        "paper_out": bool(base.get("paper_out")) or bool(extra.get("paper_out")),
        "paper_jam": bool(base.get("paper_jam")) or bool(extra.get("paper_jam")),
        "ink_shortage": bool(base.get("ink_shortage")) or bool(extra.get("ink_shortage")),
    }


def parse_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        return int(text)
    except Exception:
        return None


def is_job_in_queue(queue_items: List[Dict[str, Any]], job_id: Any) -> bool:
    if job_id is None:
        return False
    target = str(job_id)
    for item in queue_items or []:
        if str(item.get("id", "")).strip() == target:
            return True
    return False


def match_from_detail(detail: Dict[str, Any]) -> Dict[str, bool]:
    result = {"paper_out": False, "paper_jam": False, "ink_shortage": False}

    win32_status = parse_int(detail.get("win32_status"))
    if win32_status is not None:
        if (win32_status & 0x00000040) or (win32_status in (0x00000004, 0x00000005)):
            result["paper_out"] = True
        if win32_status & 0x00000008:
            result["paper_jam"] = True

    wmi = detail.get("wmi") or {}
    detected_error_state = parse_int(wmi.get("detected_error_state"))
    if detected_error_state in (3, 4, 13, 14, 15, 20):
        result["paper_out"] = True
    if detected_error_state in (10,):
        result["paper_jam"] = True
    if detected_error_state in (16, 17, 18, 19):
        result["ink_shortage"] = True

    return result


def pick_printer(pm: PrinterManager, preferred_name: Optional[str]) -> Tuple[Optional[str], List[str]]:
    managed = pm.get_printers() or []
    names = [p.get("name") for p in managed if p.get("name")]
    if preferred_name:
        for n in names:
            if n == preferred_name:
                return n, names
        return None, names
    if names:
        return names[0], names
    return None, []


def safe_get_status_detail(pm: PrinterManager, printer_name: str) -> Dict[str, Any]:
    try:
        detail = pm.get_printer_status_detail(printer_name)
        if isinstance(detail, dict):
            return detail
    except Exception:
        pass
    return {"status_text": "未知", "win32_status": None, "win32_attributes": None, "wmi": None}


def append_event(
    events: List[Dict[str, Any]],
    source: str,
    text: str,
    extra: Optional[Dict[str, Any]] = None,
    matches_extra: Optional[Dict[str, bool]] = None,
) -> None:
    text_matches = match_categories(text)
    all_matches = merge_matches(text_matches, matches_extra or {})
    row = {
        "timestamp": now_iso(),
        "source": source,
        "text": str(text),
        "matches": all_matches,
    }
    if extra:
        row["extra"] = extra
    events.append(row)


def build_report(
    printer_name: str,
    all_printers: List[str],
    trigger_print: bool,
    submit_result: Dict[str, Any],
    local_job_id: Optional[int],
    monitor_seconds: int,
    poll_interval: float,
    project_rule_support: Dict[str, bool],
    observed: Dict[str, bool],
    events: List[Dict[str, Any]],
    continuous: bool,
    run_seconds: int,
    interrupted: bool,
) -> Dict[str, Any]:
    return {
        "success": True,
        "time": now_iso(),
        "platform": platform.platform(),
        "printer_name": printer_name,
        "all_managed_printers": all_printers,
        "trigger_print": trigger_print,
        "submit_result": submit_result,
        "local_job_id": local_job_id,
        "monitor_seconds": monitor_seconds,
        "poll_interval": poll_interval,
        "continuous": continuous,
        "run_seconds": run_seconds,
        "interrupted": interrupted,
        "project_rule_support": project_rule_support,
        "runtime_observed": observed,
        "can_detect_now": {
            "paper_out": project_rule_support["paper_out"] and observed["paper_out"],
            "paper_jam": project_rule_support["paper_jam"] and observed["paper_jam"],
            "ink_shortage": project_rule_support["ink_shortage"] and observed["ink_shortage"],
        },
        "events_count": len(events),
        "events": events,
    }


def flush_report(path: str, report: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--printer-name", type=str, default=None)
    parser.add_argument("--pdf-path", type=str, default="test.pdf")
    parser.add_argument("--trigger-print", action="store_true")
    parser.add_argument("--monitor-seconds", type=int, default=180)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--output", type=str, default="error_detection_report.json")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--save-every", type=int, default=15)
    parser.add_argument("--max-events", type=int, default=5000)
    parser.add_argument("--stall-seconds", type=int, default=45)
    parser.add_argument("--print-live", action="store_true")
    args = parser.parse_args()

    pm = PrinterManager()
    printer_name, all_printers = pick_printer(pm, args.printer_name)
    if not printer_name:
        report = {
            "success": False,
            "message": "未找到可用打印机，请先在Edge管理列表中添加打印机",
            "all_managed_printers": all_printers,
            "time": now_iso(),
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    local_job_id = None
    submit_result: Dict[str, Any] = {"success": False, "message": "未触发打印"}
    if args.trigger_print:
        if not os.path.exists(args.pdf_path):
            report = {
                "success": False,
                "message": f"未找到测试文件: {args.pdf_path}",
                "printer_name": printer_name,
                "time": now_iso(),
            }
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        job_name = f"ErrorProbe_{int(time.time())}"
        submit_result = pm.submit_print_job_with_cleanup(
            printer_name=printer_name,
            file_path=args.pdf_path,
            job_name=job_name,
            print_options={},
            cleanup_source="错误检测脚本",
        )
        local_job_id = submit_result.get("job_id")

    events: List[Dict[str, Any]] = []
    observed = {"paper_out": False, "paper_jam": False, "ink_shortage": False}
    start = time.time()
    end_time = None if args.continuous else (start + max(1, args.monitor_seconds))
    next_save_time = start + max(1, args.save_every)
    last_printer_text = ""
    last_queue_text = ""
    last_job_text = ""
    last_detail_matches = {"paper_out": False, "paper_jam": False, "ink_shortage": False}
    last_pages_printed: Optional[int] = None
    stall_start_at: Optional[float] = None
    stall_alerted = False
    interrupted = False
    project_rule_support = {
        "paper_out": True,
        "paper_jam": True,
        "ink_shortage": False,
    }

    try:
        while True:
            if end_time is not None and time.time() >= end_time:
                break

            detail = safe_get_status_detail(pm, printer_name)
            printer_text = str(detail.get("status_text", "未知"))
            detail_matches = match_from_detail(detail)
            if printer_text != last_printer_text or detail_matches != last_detail_matches:
                append_event(
                    events,
                    "printer_status",
                    printer_text,
                    {"detail": detail},
                    matches_extra=detail_matches,
                )
                last_printer_text = printer_text
                last_detail_matches = detail_matches
                if args.print_live:
                    print(f"[{now_iso()}] printer_status -> {printer_text} | raw={detail_matches}")
            merged_printer_matches = merge_matches(match_categories(printer_text), detail_matches)
            for k, v in merged_printer_matches.items():
                observed[k] = observed[k] or v

            queue_items = pm.get_print_queue(printer_name) or []
            for item in queue_items:
                queue_text = str(item.get("status", ""))
                if queue_text and queue_text != last_queue_text:
                    append_event(events, "queue_status", queue_text, {"queue_item": item})
                    last_queue_text = queue_text
                    if args.print_live:
                        print(f"[{now_iso()}] queue_status -> {queue_text}")
                for k, v in match_categories(queue_text).items():
                    observed[k] = observed[k] or v

            if local_job_id:
                js = pm.get_job_status(printer_name, local_job_id)
                job_text = str(js.get("status", ""))
                if job_text != last_job_text:
                    append_event(events, "job_status", job_text, {"job": js, "job_id": local_job_id})
                    last_job_text = job_text
                    if args.print_live:
                        print(f"[{now_iso()}] job_status -> {job_text}")
                for k, v in match_categories(job_text).items():
                    observed[k] = observed[k] or v

                if js.get("exists", False):
                    current_pages = js.get("pages_printed")
                    if isinstance(current_pages, int):
                        if last_pages_printed is None or current_pages > last_pages_printed:
                            last_pages_printed = current_pages
                            stall_start_at = None
                            stall_alerted = False
                        else:
                            total_pages = parse_int(js.get("total_pages"))
                            if total_pages is not None and current_pages >= total_pages:
                                stall_start_at = None
                                stall_alerted = False
                                continue
                            active_text = normalize_text(job_text)
                            is_active = ("打印" in active_text) or ("processing" in active_text) or ("后台" in active_text) or ("unknown" in active_text) or ("未知" in active_text)
                            in_queue = is_job_in_queue(queue_items, local_job_id)
                            if is_active and in_queue:
                                if stall_start_at is None:
                                    stall_start_at = time.time()
                                elif (time.time() - stall_start_at) >= max(10, args.stall_seconds) and not stall_alerted:
                                    suspect_matches = {"paper_out": True, "paper_jam": False, "ink_shortage": False}
                                    msg = f"任务页数停滞超过{args.stall_seconds}s且任务仍在队列，疑似缺纸"
                                    append_event(
                                        events,
                                        "stall_suspect",
                                        msg,
                                        {"job": js, "job_id": local_job_id},
                                        matches_extra=suspect_matches,
                                    )
                                    observed["paper_out"] = True
                                    stall_alerted = True
                else:
                    last_pages_printed = None
                    stall_start_at = None
                    stall_alerted = False

            if len(events) > max(100, args.max_events):
                events = events[-args.max_events :]

            if time.time() >= next_save_time:
                report = build_report(
                    printer_name=printer_name,
                    all_printers=all_printers,
                    trigger_print=bool(args.trigger_print),
                    submit_result=submit_result,
                    local_job_id=local_job_id,
                    monitor_seconds=args.monitor_seconds,
                    poll_interval=args.poll_interval,
                    project_rule_support=project_rule_support,
                    observed=observed,
                    events=events,
                    continuous=bool(args.continuous),
                    run_seconds=int(time.time() - start),
                    interrupted=False,
                )
                flush_report(args.output, report)
                next_save_time = time.time() + max(1, args.save_every)
                if args.print_live:
                    print(f"[{now_iso()}] 已落盘: {args.output}")

            time.sleep(max(0.2, args.poll_interval))
    except KeyboardInterrupt:
        interrupted = True

    report = build_report(
        printer_name=printer_name,
        all_printers=all_printers,
        trigger_print=bool(args.trigger_print),
        submit_result=submit_result,
        local_job_id=local_job_id,
        monitor_seconds=args.monitor_seconds,
        poll_interval=args.poll_interval,
        project_rule_support=project_rule_support,
        observed=observed,
        events=events,
        continuous=bool(args.continuous),
        run_seconds=int(time.time() - start),
        interrupted=interrupted,
    )
    flush_report(args.output, report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
