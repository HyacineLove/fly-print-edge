import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_windows import WindowsEnterprisePrinter


class FakeWin32Print:
    PRINTER_ACCESS_USE = 0x00000008
    PRINTER_ALL_ACCESS = 0x000F000C
    PRINTER_ENUM_LOCAL = 0x00000002
    PRINTER_ENUM_CONNECTIONS = 0x00000004
    JOB_CONTROL_DELETE = 5

    def __init__(self, jobs_by_call=None, printers=None, enum_jobs_error=None):
        self.jobs_by_call = list(jobs_by_call or [])
        self.enum_jobs_error = enum_jobs_error
        self.printers = printers or [
            (0, None, "HP LaserJet Pro 3288dn", "HP LaserJet Pro 3288dn"),
        ]
        self.opened = []
        self.set_job_calls = []

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

    def SetJob(self, handle, job_id, level, job_info, command):
        self.set_job_calls.append((handle, job_id, level, job_info, command))

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

    def test_pdf_explicit_sumatra_failure_does_not_call_bitmap_fallback(self):
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
                {"pdf_engine": "sumatra", "pdf_bitmap_fallback": True},
            )

        self.assertFalse(result["success"])
        bitmap_mock.assert_not_called()

    def test_pdf_default_engine_uses_bitmap_without_resolving_sumatra(self):
        printer = self.make_printer()

        with patch.object(printer, "_find_sumatra_pdf_path") as sumatra_mock, \
             patch.object(
                 printer,
                 "_print_pdf_file_bitmap",
                 return_value={"success": True, "job_id": 42, "message": "bitmap"},
             ) as bitmap_mock:
            result = printer._print_pdf_file(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                "target.pdf",
                {},
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(42, result["job_id"])
        bitmap_mock.assert_called_once_with("HP LaserJet Pro 3288dn", os.path.abspath("target.pdf"), "target.pdf", {})
        sumatra_mock.assert_not_called()

    def run_pdf_bitmap_with_fake_printer_dpi(self, printer_dpi_x, printer_dpi_y, print_options=None):
        printer = self.make_printer()
        matrix_calls = []

        class FakePixmap:
            width = 600
            height = 900
            samples = b"\xff" * (600 * 900 * 3)

        class FakePage:
            rect = types.SimpleNamespace(width=288.0, height=432.0)

            def get_pixmap(self, matrix=None, alpha=False):
                return FakePixmap()

        class FakeDocument:
            def __len__(self):
                return 1

            def load_page(self, index):
                return FakePage()

            def close(self):
                return None

        class FakeMemDc:
            def SelectObject(self, obj):
                return "old"

            def DeleteDC(self):
                return None

        class FakeHdc:
            def CreatePrinterDC(self, printer_name):
                return None

            def StartDoc(self, job_name):
                return 777

            def StartPage(self):
                return None

            def GetDeviceCaps(self, cap):
                values = {
                    8: 2480,
                    10: 3507,
                    88: printer_dpi_x,
                    90: printer_dpi_y,
                }
                return values[cap]

            def CreateCompatibleDC(self):
                return FakeMemDc()

            def StretchBlt(self, *args):
                return None

            def EndPage(self):
                return None

            def EndDoc(self):
                return None

            def DeleteDC(self):
                return None

        fake_win32print = types.SimpleNamespace(
            PRINTER_ACCESS_USE=8,
            OpenPrinter=Mock(return_value="printer-handle"),
            ClosePrinter=Mock(),
            GetPrinter=Mock(return_value={"pDevMode": None}),
        )
        fake_win32ui = types.SimpleNamespace(
            CreateDC=lambda: FakeHdc(),
            CreateDCFromHandle=lambda handle: FakeHdc(),
            CreateBitmapFromHandle=lambda handle: f"bitmap-{handle}",
        )
        fake_win32con = types.SimpleNamespace(
            HORZRES=8,
            VERTRES=10,
            LOGPIXELSX=88,
            LOGPIXELSY=90,
            SRCCOPY=0x00CC0020,
            DMPAPER_A4=9,
            DMPAPER_LETTER=1,
            DMPAPER_LEGAL=5,
            DMPAPER_A3=8,
            DMPAPER_A5=11,
            DM_PAPERSIZE=0x2,
            DMDUP_SIMPLEX=1,
            DMDUP_VERTICAL=2,
            DMDUP_HORIZONTAL=3,
            DM_DUPLEX=0x1000,
            DMCOLOR_MONOCHROME=1,
            DMCOLOR_COLOR=2,
            DM_COLOR=0x800,
            DM_COPIES=0x100,
        )
        fake_win32gui = types.SimpleNamespace(
            CreateDC=Mock(return_value="hdc-handle"),
            LoadImage=Mock(return_value="hbmp"),
            DeleteObject=Mock(),
        )

        def fake_matrix(x, y):
            matrix_calls.append((x, y))
            return (x, y)

        fake_fitz = types.SimpleNamespace(
            Matrix=fake_matrix,
            open=Mock(return_value=FakeDocument()),
        )

        with patch("printer_windows.win32print", fake_win32print, create=True), \
             patch.dict(
                 sys.modules,
                 {
                     "win32ui": fake_win32ui,
                     "win32con": fake_win32con,
                     "win32gui": fake_win32gui,
                     "fitz": fake_fitz,
                 },
             ), \
             patch.object(
                 printer,
                 "_prepare_print_job_tracking",
                 return_value={"queue_name": "HP LaserJet Pro 3288dn", "before_job_ids": {1}},
             ), \
             patch.object(printer, "_get_latest_job_id", return_value=42), \
             patch.object(printer, "_get_setting", return_value=None):
            result = printer._print_pdf_file_bitmap(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                "target.pdf",
                print_options or {},
            )

        return result, matrix_calls

    def test_pdf_bitmap_default_render_dpi_uses_target_printer_dpi(self):
        result, matrix_calls = self.run_pdf_bitmap_with_fake_printer_dpi(600, 600)

        self.assertTrue(result["success"], result)
        self.assertEqual([(600 / 72.0, 600 / 72.0)], matrix_calls)

    def test_pdf_bitmap_explicit_render_dpi_can_lower_printer_dpi(self):
        result, matrix_calls = self.run_pdf_bitmap_with_fake_printer_dpi(
            600,
            600,
            {"pdf_bitmap_dpi": 300},
        )

        self.assertTrue(result["success"], result)
        self.assertEqual([(300 / 72.0, 300 / 72.0)], matrix_calls)

    def test_pdf_bitmap_explicit_render_dpi_is_clamped_to_printer_dpi(self):
        result, matrix_calls = self.run_pdf_bitmap_with_fake_printer_dpi(
            600,
            600,
            {"pdf_bitmap_dpi": 1200},
        )

        self.assertTrue(result["success"], result)
        self.assertEqual([(600 / 72.0, 600 / 72.0)], matrix_calls)

    def test_pdf_bitmap_invalid_printer_dpi_falls_back_to_300(self):
        result, matrix_calls = self.run_pdf_bitmap_with_fake_printer_dpi(0, 0)

        self.assertTrue(result["success"], result)
        self.assertEqual([(300 / 72.0, 300 / 72.0)], matrix_calls)

    def test_pdf_bitmap_print_uses_queue_tracked_job_id_and_physical_draw_size(self):
        printer = self.make_printer()
        stretch_calls = []

        class FakePixmap:
            width = 600
            height = 900
            samples = b"\xff" * (600 * 900 * 3)

        class FakePage:
            rect = types.SimpleNamespace(width=288.0, height=432.0)

            def get_pixmap(self, matrix=None, alpha=False):
                return FakePixmap()

        class FakeDocument:
            def __len__(self):
                return 1

            def load_page(self, index):
                return FakePage()

            def close(self):
                return None

        class FakeMemDc:
            def SelectObject(self, obj):
                return "old"

            def DeleteDC(self):
                return None

        class FakeHdc:
            def CreatePrinterDC(self, printer_name):
                return None

            def StartDoc(self, job_name):
                return 777

            def StartPage(self):
                return None

            def GetDeviceCaps(self, cap):
                values = {
                    8: 2480,
                    10: 3507,
                    88: 300,
                    90: 300,
                }
                return values[cap]

            def CreateCompatibleDC(self):
                return FakeMemDc()

            def StretchBlt(self, dst_pos, dst_size, *args):
                stretch_calls.append((dst_pos, dst_size))

            def EndPage(self):
                return None

            def EndDoc(self):
                return None

            def DeleteDC(self):
                return None

        fake_win32print = types.SimpleNamespace(
            PRINTER_ACCESS_USE=8,
            OpenPrinter=Mock(return_value="printer-handle"),
            ClosePrinter=Mock(),
            GetPrinter=Mock(return_value={"pDevMode": None}),
        )
        fake_win32ui = types.SimpleNamespace(
            CreateDC=lambda: FakeHdc(),
            CreateDCFromHandle=lambda handle: FakeHdc(),
            CreateBitmapFromHandle=lambda handle: f"bitmap-{handle}",
        )
        fake_win32con = types.SimpleNamespace(
            HORZRES=8,
            VERTRES=10,
            LOGPIXELSX=88,
            LOGPIXELSY=90,
            SRCCOPY=0x00CC0020,
            DMPAPER_A4=9,
            DMPAPER_LETTER=1,
            DMPAPER_LEGAL=5,
            DMPAPER_A3=8,
            DMPAPER_A5=11,
            DM_PAPERSIZE=0x2,
            DMDUP_SIMPLEX=1,
            DMDUP_VERTICAL=2,
            DMDUP_HORIZONTAL=3,
            DM_DUPLEX=0x1000,
            DMCOLOR_MONOCHROME=1,
            DMCOLOR_COLOR=2,
            DM_COLOR=0x800,
            DM_COPIES=0x100,
        )
        fake_win32gui = types.SimpleNamespace(
            CreateDC=Mock(return_value="hdc-handle"),
            LoadImage=Mock(return_value="hbmp"),
            DeleteObject=Mock(),
        )
        fake_fitz = types.SimpleNamespace(
            Matrix=lambda x, y: (x, y),
            open=Mock(return_value=FakeDocument()),
        )

        with patch("printer_windows.win32print", fake_win32print, create=True), \
             patch.dict(
                 sys.modules,
                 {
                     "win32ui": fake_win32ui,
                     "win32con": fake_win32con,
                     "win32gui": fake_win32gui,
                     "fitz": fake_fitz,
                 },
             ), \
             patch.object(
                 printer,
                 "_prepare_print_job_tracking",
                 return_value={"queue_name": "HP LaserJet Pro 3288dn", "before_job_ids": {1}},
             ) as tracking_mock, \
             patch.object(printer, "_get_latest_job_id", return_value=42) as latest_mock:
            result = printer._print_pdf_file_bitmap(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                "target.pdf",
                {},
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(42, result["job_id"])
        tracking_mock.assert_called_once_with("HP LaserJet Pro 3288dn", "target.pdf")
        latest_mock.assert_called_once_with(
            "HP LaserJet Pro 3288dn",
            "target.pdf",
            before_job_ids={1},
        )
        self.assertEqual([((640, 853), (1200, 1800))], stretch_calls)

    def test_pdf_system_engine_does_not_call_shellexecute(self):
        printer = self.make_printer()
        shell_execute = Mock(side_effect=AssertionError("ShellExecute must not be used"))

        with patch.dict(
            sys.modules,
            {
                "win32api": types.SimpleNamespace(ShellExecute=shell_execute),
                "win32print": types.SimpleNamespace(),
            },
        ), \
             patch.object(printer, "_find_sumatra_pdf_path", return_value="SumatraPDF.exe"), \
             patch.object(printer, "_prepare_print_job_tracking") as tracking_mock:
            result = printer._print_pdf_file(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                "target.pdf",
                {"pdf_engine": "system"},
            )

        self.assertFalse(result["success"])
        self.assertIn("PDF打印引擎不支持", result["message"])
        shell_execute.assert_not_called()
        tracking_mock.assert_not_called()

    def test_pdf_explicit_sumatra_missing_fails_without_system_application_fallback(self):
        printer = self.make_printer()
        shell_execute = Mock()

        with patch.dict(
            sys.modules,
            {
                "win32api": types.SimpleNamespace(ShellExecute=shell_execute),
                "win32print": types.SimpleNamespace(),
            },
        ), \
             patch.object(printer, "_find_sumatra_pdf_path", return_value=None), \
             patch.object(printer, "_prepare_print_job_tracking") as tracking_mock:
            result = printer._print_pdf_file(
                "HP LaserJet Pro 3288dn",
                "target.pdf",
                "target.pdf",
                {"pdf_engine": "sumatra"},
            )

        self.assertFalse(result["success"])
        self.assertIn("SumatraPDF不可用", result["message"])
        shell_execute.assert_not_called()
        tracking_mock.assert_not_called()

    def test_image_print_returns_queue_tracked_job_id_not_startdoc_value(self):
        printer = self.make_printer()

        class FakeMemDc:
            def SelectObject(self, obj):
                return "old-bitmap"

            def DeleteDC(self):
                return None

        class FakeHdc:
            def CreatePrinterDC(self, printer_name):
                self.printer_name = printer_name

            def StartDoc(self, job_name):
                return 777

            def StartPage(self):
                return None

            def GetDeviceCaps(self, cap):
                if cap == 8:
                    return 2400
                if cap == 10:
                    return 3300
                if cap in (88, 90):
                    return 300
                return 0

            def CreateCompatibleDC(self):
                return FakeMemDc()

            def StretchBlt(self, *args, **kwargs):
                return None

            def EndPage(self):
                return None

            def EndDoc(self):
                return None

            def DeleteDC(self):
                return None

        fake_win32print = types.SimpleNamespace(
            PRINTER_ACCESS_USE=8,
            OpenPrinter=Mock(return_value="printer-handle"),
            ClosePrinter=Mock(),
        )
        fake_win32ui = types.SimpleNamespace(
            CreateDC=lambda: FakeHdc(),
            CreateBitmapFromHandle=lambda handle: f"bitmap-{handle}",
        )
        fake_win32con = types.SimpleNamespace(HORZRES=8, VERTRES=10, LOGPIXELSX=88, LOGPIXELSY=90, SRCCOPY=0x00CC0020)
        fake_win32gui = types.SimpleNamespace(
            LoadImage=Mock(return_value="hbmp"),
            DeleteObject=Mock(),
        )

        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_path = tmp.name
        try:
            Image.new("RGB", (100, 200), "white").save(image_path, "JPEG")

            with patch("printer_windows.win32print", fake_win32print, create=True), \
                 patch.dict(
                     sys.modules,
                     {
                         "win32ui": fake_win32ui,
                         "win32con": fake_win32con,
                         "win32gui": fake_win32gui,
                     },
                 ), \
                 patch.object(
                     printer,
                     "_prepare_print_job_tracking",
                     return_value={"queue_name": "HP LaserJet Pro 3288dn", "before_job_ids": {1}},
                 ) as tracking_mock, \
                 patch.object(printer, "_get_latest_job_id", return_value=42) as latest_mock:
                result = printer._print_image_file(
                    "HP LaserJet Pro 3288dn",
                    image_path,
                    "photo.jpg",
                    {},
                )
        finally:
            try:
                os.unlink(image_path)
            except FileNotFoundError:
                pass

        self.assertTrue(result["success"])
        self.assertEqual(42, result["job_id"])
        tracking_mock.assert_called_once_with("HP LaserJet Pro 3288dn", "photo.jpg")
        latest_mock.assert_called_once_with(
            "HP LaserJet Pro 3288dn",
            "photo.jpg",
            before_job_ids={1},
        )

    def test_image_print_fails_when_queue_job_id_cannot_be_resolved(self):
        printer = self.make_printer()

        class FakeHdc:
            def CreatePrinterDC(self, printer_name):
                return None

            def StartDoc(self, job_name):
                return 777

            def StartPage(self):
                return None

            def GetDeviceCaps(self, cap):
                return 1200

            def CreateCompatibleDC(self):
                return types.SimpleNamespace(
                    SelectObject=lambda obj: "old",
                    DeleteDC=lambda: None,
                )

            def StretchBlt(self, *args, **kwargs):
                return None

            def EndPage(self):
                return None

            def EndDoc(self):
                return None

            def DeleteDC(self):
                return None

        fake_win32print = types.SimpleNamespace(
            PRINTER_ACCESS_USE=8,
            OpenPrinter=Mock(return_value="printer-handle"),
            ClosePrinter=Mock(),
        )
        fake_win32ui = types.SimpleNamespace(
            CreateDC=lambda: FakeHdc(),
            CreateBitmapFromHandle=lambda handle: f"bitmap-{handle}",
        )
        fake_win32con = types.SimpleNamespace(HORZRES=8, VERTRES=10, LOGPIXELSX=88, LOGPIXELSY=90, SRCCOPY=0x00CC0020)
        fake_win32gui = types.SimpleNamespace(LoadImage=Mock(return_value="hbmp"), DeleteObject=Mock())

        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_path = tmp.name
        try:
            Image.new("RGB", (100, 200), "white").save(image_path, "JPEG")

            with patch("printer_windows.win32print", fake_win32print, create=True), \
                 patch.dict(
                     sys.modules,
                     {
                         "win32ui": fake_win32ui,
                         "win32con": fake_win32con,
                         "win32gui": fake_win32gui,
                     },
                 ), \
                 patch.object(
                     printer,
                     "_prepare_print_job_tracking",
                     return_value={"queue_name": "HP LaserJet Pro 3288dn", "before_job_ids": {1}},
                 ), \
                 patch.object(printer, "_get_latest_job_id", return_value=None):
                result = printer._print_image_file(
                    "HP LaserJet Pro 3288dn",
                    image_path,
                    "photo.jpg",
                    {},
                )
        finally:
            try:
                os.unlink(image_path)
            except FileNotFoundError:
                pass

        self.assertFalse(result["success"])
        self.assertIn("无法获取本地打印任务ID", result["message"])

    def test_image_print_does_not_infer_paper_size_from_guessed_image_dpi(self):
        source = open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "printer_windows.py"),
            encoding="utf-8",
        ).read()

        self.assertNotIn("img.width / 96.0", source)
        self.assertNotIn("img.height / 96.0", source)

    def test_remove_print_job_deletes_existing_job_and_confirms_removed(self):
        fake = FakeWin32Print(jobs_by_call=[
            [{"JobId": 42, "pDocument": "target.pdf", "Status": 0}],
            [],
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True), \
             patch("time.sleep") as sleep_mock:
            success, message = printer.remove_print_job("HP LaserJet Pro 3288dn", "42")

        self.assertTrue(success)
        self.assertIn("cancelled", message)
        self.assertEqual(
            [("HP LaserJet Pro 3288dn", 42, 0, None, fake.JOB_CONTROL_DELETE)],
            fake.set_job_calls,
        )
        sleep_mock.assert_not_called()

    def test_remove_print_job_fails_when_target_job_is_missing(self):
        fake = FakeWin32Print(jobs_by_call=[[]])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True):
            success, message = printer.remove_print_job("HP LaserJet Pro 3288dn", "42")

        self.assertFalse(success)
        self.assertIn("not found", message)
        self.assertEqual([], fake.set_job_calls)

    def test_remove_print_job_fails_when_cancel_confirmation_times_out(self):
        fake = FakeWin32Print(jobs_by_call=[
            [{"JobId": 42, "pDocument": "target.pdf", "Status": 0}],
            [{"JobId": 42, "pDocument": "target.pdf", "Status": 0}],
            [{"JobId": 42, "pDocument": "target.pdf", "Status": 0}],
        ])
        printer = self.make_printer()

        with patch("printer_windows.win32print", fake, create=True), \
             patch("time.sleep"):
            success, message = printer.remove_print_job(
                "HP LaserJet Pro 3288dn",
                "42",
                confirm_timeout=0.0,
            )

        self.assertFalse(success)
        self.assertIn("timeout", message)
        self.assertEqual(1, len(fake.set_job_calls))


if __name__ == "__main__":
    unittest.main()
