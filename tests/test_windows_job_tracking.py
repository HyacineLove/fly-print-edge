import os
import sys
import types
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_windows import WindowsEnterprisePrinter


class FakeWin32Print:
    PRINTER_ACCESS_USE = 0x00000008
    PRINTER_ENUM_LOCAL = 0x00000002
    PRINTER_ENUM_CONNECTIONS = 0x00000004

    def __init__(self, jobs_by_call=None, printers=None, enum_jobs_error=None):
        self.jobs_by_call = list(jobs_by_call or [])
        self.enum_jobs_error = enum_jobs_error
        self.printers = printers or [
            (0, None, "HP LaserJet Pro 3288dn", "HP LaserJet Pro 3288dn"),
        ]
        self.opened = []

    def EnumPrinters(self, flags):
        return self.printers

    def OpenPrinter(self, name, defaults=None):
        self.opened.append((name, defaults))
        return name

    def GetPrinter(self, handle, level):
        if level == 3:
            return {"Status": "Ready from PRINTER_INFO_3"}
        return {"pDriverName": "HP Driver", "pPortName": "IP_10.0.0.5"}

    def EnumJobs(self, handle, first, count, level):
        if self.enum_jobs_error:
            raise self.enum_jobs_error
        if self.jobs_by_call:
            return self.jobs_by_call.pop(0)
        return []

    def ClosePrinter(self, handle):
        return None


class WindowsJobTrackingTests(unittest.TestCase):
    def make_printer(self):
        printer = WindowsEnterprisePrinter()
        printer.available = True
        return printer

    def test_get_latest_job_id_does_not_guess_largest_existing_job(self):
        fake = FakeWin32Print(jobs_by_call=[
            [
                {"JobId": 41, "pDocument": "other.pdf", "Status": 0},
                {"JobId": 42, "pDocument": "unrelated.pdf", "Status": 0},
            ]
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            job_id = printer._get_latest_job_id(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                before_job_ids={41, 42},
                max_wait=0.1,
            )

        self.assertIsNone(job_id)

    def test_get_latest_job_id_returns_unique_new_matching_document(self):
        fake = FakeWin32Print(jobs_by_call=[
            [
                {"JobId": 41, "pDocument": "old.pdf", "Status": 0},
                {"JobId": 42, "pDocument": "target.pdf", "Status": 0},
            ]
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            job_id = printer._get_latest_job_id(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                before_job_ids={41},
                max_wait=0.1,
            )

        self.assertEqual(42, job_id)

    def test_get_latest_job_id_rejects_multiple_new_matching_documents(self):
        fake = FakeWin32Print(jobs_by_call=[
            [
                {"JobId": 42, "pDocument": "target.pdf", "Status": 0},
                {"JobId": 43, "pDocument": "target.pdf", "Status": 0},
            ]
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            job_id = printer._get_latest_job_id(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                before_job_ids=set(),
                max_wait=0.1,
            )

        self.assertIsNone(job_id)

    def test_resolve_windows_printer_queue_accepts_exact_match(self):
        fake = FakeWin32Print(printers=[
            (0, None, "HP LaserJet Pro 3288dn", ""),
            (0, None, "Other Printer", ""),
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            resolved = printer._resolve_windows_printer_queue("HP LaserJet Pro 3288dn")

        self.assertEqual("HP LaserJet Pro 3288dn", resolved["name"])

    def test_resolve_windows_printer_queue_accepts_casefold_match(self):
        fake = FakeWin32Print(printers=[
            (0, None, "HP LaserJet Pro 3288dn", ""),
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            resolved = printer._resolve_windows_printer_queue("hp laserjet pro 3288DN")

        self.assertEqual("HP LaserJet Pro 3288dn", resolved["name"])

    def test_resolve_windows_printer_queue_rejects_unique_contains_match(self):
        fake = FakeWin32Print(printers=[
            (0, None, "HPIA24DD9 (HP Color LaserJet Pro 3288)", ""),
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            resolved = printer._resolve_windows_printer_queue("HP Color LaserJet Pro 3288")

        self.assertIsNone(resolved)

    def test_resolve_windows_printer_queue_rejects_ambiguous_exact_match(self):
        fake = FakeWin32Print(printers=[
            (0, None, "HP LaserJet Pro 3288dn", ""),
            (0, None, "HP LaserJet Pro 3288dn", ""),
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            resolved = printer._resolve_windows_printer_queue("HP LaserJet Pro 3288dn")

        self.assertIsNone(resolved)

    def test_get_latest_job_id_fails_fast_when_enum_jobs_dependency_missing(self):
        fake = FakeWin32Print(enum_jobs_error=ModuleNotFoundError("win32timezone"))
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True), \
             patch("time.sleep") as sleep_mock:
            job_id = printer._get_latest_job_id(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                before_job_ids=set(),
                max_wait=5.0,
            )

        self.assertIsNone(job_id)
        sleep_mock.assert_not_called()

    def test_document_name_matching_does_not_accept_substring(self):
        printer = self.make_printer()

        self.assertFalse(
            printer._document_matches_job_name("my-target.pdf", "target.pdf")
        )

    def test_get_printer_status_detail_can_use_info3_without_name_error(self):
        fake = FakeWin32Print()
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True), \
             patch.object(printer, "_get_wmi_printer_status_detail", return_value=None):
            status = printer.get_printer_status_detail("HP LaserJet Pro 3288dn")

        self.assertEqual("Ready from PRINTER_INFO_3", status["status_text"])

    def test_pdf_sumatra_failure_does_not_call_bitmap_fallback(self):
        printer = self.make_printer()
        completed = types.SimpleNamespace(returncode=1, stdout="sumatra failed", stderr="")

        with patch.dict(
            sys.modules,
            {
                "win32api": types.SimpleNamespace(),
                "win32print": types.SimpleNamespace(),
            },
        ), \
             patch.object(printer, "_find_sumatra_pdf_path", return_value="SumatraPDF.exe"), \
             patch.object(
                 printer,
                 "_prepare_print_job_tracking",
                 return_value={
                     "queue_name": "HP LaserJet Pro 3288dn",
                     "driver": "HP Driver",
                     "port": "IP_10.0.0.5",
                     "before_job_ids": set(),
                 },
             ), \
             patch.object(printer, "_detect_file_paper_size", return_value=None), \
             patch.object(printer, "_resolve_print_orientation", return_value=None), \
             patch.object(printer, "_print_pdf_file_bitmap") as bitmap_mock, \
             patch("subprocess.run", return_value=completed):
            result = printer._print_pdf_file(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                "target.pdf",
                {"pdf_bitmap_fallback": True},
            )

        self.assertFalse(result["success"])
        bitmap_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
