import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud_websocket_client import PrintJobHandler
from printer_fault_state import PrinterFaultStateStore


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


class DummyConfig:
    def __init__(self):
        self.printer = {
            "id": "printer-1",
            "name": "Microsoft Print to PDF",
            "location": "http://169.254.12.234:3911",
        }

    def get_printer_by_id(self, printer_id):
        return self.printer if printer_id == self.printer["id"] else None

    def get_printer_by_name(self, printer_name):
        return self.printer if printer_name == self.printer["name"] else None


class MonitorPrinterManager:
    def __init__(self, job_statuses, remove_result=(True, "cancelled")):
        self.config = DummyConfig()
        self.job_statuses = list(job_statuses)
        self.remove_result = remove_result
        self.cancelled = []

    def get_job_status(self, printer_name, local_job_id):
        if self.job_statuses:
            return self.job_statuses.pop(0)
        return {"exists": True, "status": "printing"}

    def remove_print_job(self, printer_name, local_job_id):
        self.cancelled.append((printer_name, local_job_id))
        return self.remove_result


class ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


class StaticFaultProbe:
    def __init__(self, result):
        self.result = result
        self.hosts = []

    def probe(self, host):
        self.hosts.append(host)
        return self.result


class FakeWebSocketClient:
    def __init__(self):
        self.sent_messages = []
        self.local_messages = []

    def send_message_sync(self, message):
        self.sent_messages.append(message)
        return True

    def dispatch_local_message(self, message_type, message):
        self.local_messages.append((message_type, message))


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

    def test_monitor_cancels_local_job_before_reporting_ipp_fault(self):
        fault_result = SimpleNamespace(
            available=True,
            faulted=True,
            fault_reasons=["media-empty-error", "media-needed-error"],
            printer_state=5,
            printer_state_name="stopped",
            error="",
        )
        printer_manager = MonitorPrinterManager([
            {"exists": True, "status": "printing"},
        ])
        fault_probe = StaticFaultProbe(fault_result)
        status_reporter = Mock()
        handler = PrintJobHandler(
            printer_manager=printer_manager,
            api_client=None,
            status_reporter=status_reporter,
            fault_probe=fault_probe,
        )

        with patch("threading.Thread", ImmediateThread), \
             patch("time.sleep"), \
             patch.object(handler, "_report_job_failure") as failure_mock, \
             patch.object(handler, "_report_job_success") as success_mock:
            handler._monitor_job_completion(
                "cloud-job-1",
                "Microsoft Print to PDF",
                42,
                "printer-1",
            )

        self.assertEqual([("Microsoft Print to PDF", 42)], printer_manager.cancelled)
        self.assertEqual(["169.254.12.234"], fault_probe.hosts)
        success_mock.assert_not_called()
        failure_mock.assert_called_once()
        self.assertIn("缺纸", failure_mock.call_args.args[1])
        status_reporter.force_report_printer.assert_called_with(
            printer_id="printer-1",
            printer_name="Microsoft Print to PDF",
        )

    def test_monitor_fault_failure_sends_mapped_local_payload_and_preserves_raw_reasons(self):
        fault_result = SimpleNamespace(
            available=True,
            faulted=True,
            fault_reasons=["media-empty-error", "media-needed-error"],
            printer_state=5,
            printer_state_name="stopped",
            error="",
        )
        websocket = FakeWebSocketClient()
        handler = PrintJobHandler(
            printer_manager=MonitorPrinterManager([
                {"exists": True, "status": "printing"},
            ]),
            api_client=None,
            websocket_client=websocket,
            fault_probe=StaticFaultProbe(fault_result),
            fault_state_store=PrinterFaultStateStore(),
        )

        with patch("threading.Thread", ImmediateThread), patch("time.sleep"):
            handler._monitor_job_completion(
                "cloud-job-1",
                "Microsoft Print to PDF",
                42,
                "printer-1",
            )

        self.assertEqual(1, len(websocket.sent_messages))
        cloud_data = websocket.sent_messages[0]["data"]
        self.assertEqual("failed", cloud_data["status"])
        self.assertEqual("打印机缺纸，请联系管理员补纸", cloud_data["error_message"])
        self.assertNotIn("printer_fault", cloud_data)

        self.assertEqual("job_status", websocket.local_messages[0][0])
        local_data = websocket.local_messages[0][1]["data"]
        self.assertEqual("printer_fault", local_data["error_code"])
        self.assertEqual("打印机缺纸，请联系管理员补纸", local_data["message"])
        self.assertEqual(
            ["media-empty-error", "media-needed-error"],
            local_data["printer_fault"]["raw_reasons"],
        )

    def test_monitor_does_not_fail_when_fault_probe_is_unavailable(self):
        unavailable = SimpleNamespace(
            available=False,
            faulted=False,
            fault_reasons=[],
            printer_state=None,
            printer_state_name="unknown",
            error="connection refused",
        )
        printer_manager = MonitorPrinterManager([
            {"exists": True, "status": "printing"},
            {"exists": False, "status": "completed_or_failed"},
        ])
        handler = PrintJobHandler(
            printer_manager=printer_manager,
            api_client=None,
            fault_probe=StaticFaultProbe(unavailable),
        )

        with patch("threading.Thread", ImmediateThread), \
             patch("time.sleep"), \
             patch.object(handler, "_report_job_failure") as failure_mock, \
             patch.object(handler, "_report_job_success") as success_mock:
            handler._monitor_job_completion(
                "cloud-job-1",
                "Microsoft Print to PDF",
                42,
                "printer-1",
            )

        self.assertEqual([], printer_manager.cancelled)
        failure_mock.assert_not_called()
        success_mock.assert_called_once_with("cloud-job-1", "printer-1")

    def test_monitor_reports_success_when_job_disappears_without_fault(self):
        printer_manager = MonitorPrinterManager([
            {"exists": False, "status": "completed_or_failed"},
        ])
        handler = PrintJobHandler(
            printer_manager=printer_manager,
            api_client=None,
            fault_probe=StaticFaultProbe(SimpleNamespace(available=True, faulted=False)),
        )

        with patch("threading.Thread", ImmediateThread), \
             patch("time.sleep"), \
             patch.object(handler, "_report_job_failure") as failure_mock, \
             patch.object(handler, "_report_job_success") as success_mock:
            handler._monitor_job_completion(
                "cloud-job-1",
                "Microsoft Print to PDF",
                42,
                "printer-1",
            )

        self.assertEqual([], printer_manager.cancelled)
        failure_mock.assert_not_called()
        success_mock.assert_called_once_with("cloud-job-1", "printer-1")


if __name__ == "__main__":
    unittest.main()
