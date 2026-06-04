import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud_websocket_client import PrintJobHandler


class DummyPrinterManager:
    def __init__(self, result=None):
        self.result = result or {"success": True, "job_id": None}

    def submit_print_job_with_cleanup(
        self,
        printer_name,
        file_path,
        job_name,
        print_options=None,
        cleanup_source="unknown",
        printer_id=None,
        artifact_key=None,
    ):
        return self.result


def make_print_job_message():
    return {
        "data": {
            "job_id": "cloud-job-1",
            "printer_name": "Microsoft Print to PDF",
            "printer_id": "printer-1",
            "file_url": "https://example.com/file.jpg",
            "name": "demo.jpg",
            "print_options": {"copies": 1},
        }
    }


class PrintJobHandlerBindingTests(unittest.TestCase):
    def test_handle_print_job_uses_injected_interactive_binder(self):
        binder_calls = []

        def binder(file_url, job_id):
            binder_calls.append((file_url, job_id))
            return "session-1"

        handler = PrintJobHandler(
            printer_manager=DummyPrinterManager({"success": True, "job_id": 123}),
            api_client=None,
            interactive_job_binder=binder,
        )

        with patch.object(handler, "_download_print_file", return_value="C:\\temp\\demo.jpg"), \
             patch.object(handler, "_monitor_job_completion") as monitor_mock, \
             patch.object(handler, "_report_job_failure") as failure_mock:
            handler.handle_print_job(make_print_job_message())

        self.assertEqual(
            [("https://example.com/file.jpg", "cloud-job-1")],
            binder_calls,
        )
        monitor_mock.assert_called_once_with(
            "cloud-job-1",
            "Microsoft Print to PDF",
            123,
            "printer-1",
        )
        failure_mock.assert_not_called()

    def test_handle_print_job_reports_failure_when_local_job_id_missing(self):
        handler = PrintJobHandler(
            printer_manager=DummyPrinterManager({"success": True, "job_id": None}),
            api_client=None,
        )

        with patch.object(handler, "_download_print_file", return_value="C:\\temp\\demo.jpg"), \
             patch.object(handler, "_monitor_job_completion") as monitor_mock, \
             patch.object(handler, "_report_job_failure") as failure_mock:
            handler.handle_print_job(make_print_job_message())

        monitor_mock.assert_not_called()
        failure_mock.assert_called_once_with("cloud-job-1", "无法获取本地打印任务ID")


if __name__ == "__main__":
    unittest.main()
