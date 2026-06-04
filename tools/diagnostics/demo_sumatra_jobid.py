"""
诊断 SumatraPDF 打印到 Windows spooler 后的本地 job_id 捕获链路。

用法（目标机）:
    venv\\Scripts\\python.exe tools\\diagnostics\\demo_sumatra_jobid.py
"""

import os
import subprocess
import sys
import time

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_windows import WindowsEnterprisePrinter


PRINTER_NAME = "HPIA24DD9 (HP Color LaserJet Pro 3288)"


def create_test_pdf() -> str:
    path = os.path.join(os.environ.get("TEMP", "."), "_demo_test_print.pdf")
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()
    print(f"created_pdf path={path!r}")
    return path


def find_sumatra() -> str:
    candidates = [
        os.path.join(os.getcwd(), "portable", "SumatraPDF", "SumatraPDF.exe"),
        os.path.join(os.path.dirname(sys.executable), "portable", "SumatraPDF", "SumatraPDF.exe"),
        os.path.join(os.path.dirname(sys.executable), "_internal", "portable", "SumatraPDF", "SumatraPDF.exe"),
    ]
    try:
        import json

        config_path = os.path.join(os.getcwd(), "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)
            configured = config.get("settings", {}).get("pdf_printer_path", "")
            if configured:
                candidates.insert(0, os.path.expandvars(configured))
    except Exception as e:
        print(f"job_id_debug config_read_error error={e}")

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def print_jobs(label: str, jobs):
    print(f"{label} count={len(jobs)}")
    for job in jobs:
        print(
            "  "
            f"JobId={job.get('JobId')} "
            f"pDocument={job.get('pDocument', '')!r} "
            f"Status={job.get('Status')}"
        )


def main():
    printer = WindowsEnterprisePrinter()
    test_pdf = create_test_pdf()

    try:
        sumatra = find_sumatra()
        if not sumatra:
            print("job_id_debug sumatra_not_found")
            return 1
        print(f"sumatra path={sumatra!r}")
        print(f"requested_printer={PRINTER_NAME!r}")

        resolved = printer._resolve_windows_printer_queue(PRINTER_NAME)
        if not resolved:
            print("job_id_debug printer_name_not_found_or_ambiguous")
            return 1

        queue_name = resolved["name"]
        print(
            "job_id_debug resolved_queue "
            f"name={queue_name!r} driver={resolved.get('driver')!r} port={resolved.get('port')!r}"
        )

        before_jobs = printer._enum_print_jobs_raw(queue_name)
        before_ids = {job.get("JobId") for job in before_jobs if job.get("JobId") is not None}
        print_jobs("job_id_debug before_queue", before_jobs)

        cmd = [sumatra, "-print-to", queue_name, "-silent", "-exit-when-done", test_pdf]
        print(f"job_id_debug sumatra_command cmd={cmd!r}")
        start = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=60,
        )
        elapsed = time.time() - start
        print(
            "job_id_debug sumatra_result "
            f"returncode={result.returncode} elapsed={elapsed:.1f}s "
            f"stdout={(result.stdout or '').strip()!r} stderr={(result.stderr or '').strip()!r}"
        )

        job_name = os.path.basename(test_pdf)
        job_id = printer._get_latest_job_id(
            queue_name,
            job_name,
            before_job_ids=before_ids,
            max_wait=5.0,
        )
        print(f"job_id_debug matched_job_id value={job_id!r}")

        final_jobs = printer._enum_print_jobs_raw(queue_name)
        print_jobs("job_id_debug final_queue", final_jobs)

        if not job_id:
            print("job_id_debug no_unique_matching_job")
            return 2
        return 0
    finally:
        try:
            os.remove(test_pdf)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
