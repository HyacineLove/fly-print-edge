import time
import unittest
from unittest.mock import Mock

from cloud_service import PrinterStatusReporter
from cloud_websocket_client import PrintJobHandler


class _FakeWebSocket:
    def __init__(self):
        self.cloud_messages = []
        self.local_messages = []
        self.terminal_reports = []

    def send_message_sync(self, message):
        self.cloud_messages.append(message)
        return True

    def dispatch_local_message(self, message_type, message):
        self.local_messages.append((message_type, message))

    def queue_terminal_job_update(self, job_id, status, data):
        self.terminal_reports.append((job_id, status, data))
        return True


class _FakeApiClient:
    node_id = "node-1"


class PrintJobStatusReportingTests(unittest.TestCase):
    def make_handler(self):
        return PrintJobHandler(None, _FakeApiClient(), _FakeWebSocket())

    def test_page_counts_are_local_only_while_cloud_receives_status(self):
        handler = self.make_handler()

        handler._report_job_status(
            "job-1",
            "printing",
            0,
            "打印机正在打印……",
            current_page=2,
            total_pages=5,
        )

        cloud_data = handler.websocket_client.cloud_messages[0]["data"]
        self.assertEqual("processing", cloud_data["status"])
        self.assertNotIn("current_page", cloud_data)
        self.assertNotIn("total_pages", cloud_data)

        _, local_message = handler.websocket_client.local_messages[0]
        local_data = local_message["data"]
        self.assertEqual(2, local_data["current_page"])
        self.assertEqual(5, local_data["total_pages"])

    def test_unconfirmed_error_code_is_normalized_for_cloud(self):
        handler = self.make_handler()

        handler._report_job_failure(
            "job-2",
            "无法确认打印结果",
            "ipp_submission_unconfirmed",
            status="unconfirmed",
        )

        _, status, cloud_data = handler.websocket_client.terminal_reports[0]
        self.assertEqual("unconfirmed", status)
        self.assertEqual("unconfirmed", cloud_data["status"])
        self.assertEqual("submission_unconfirmed", cloud_data["error_code"])

    def test_confirmed_failure_keeps_its_original_error_code(self):
        handler = self.make_handler()

        handler._report_job_failure(
            "job-3",
            "打印任务超时并已取消",
            "print_timeout",
            status="failed",
        )

        _, status, cloud_data = handler.websocket_client.terminal_reports[0]
        self.assertEqual("failed", status)
        self.assertEqual("failed", cloud_data["status"])
        self.assertEqual("print_timeout", cloud_data["error_code"])


class UploadTokenResponseCorrelationTests(unittest.TestCase):
    def make_handler(self):
        handler = PrintJobHandler.__new__(PrintJobHandler)
        handler.websocket_client = None
        handler.upload_token_request_id = "request-1"
        handler.upload_token_callback = Mock()
        handler.upload_token_error_callback = Mock()
        handler.last_upload_token = None
        return handler

    def test_matching_dispatch_error_completes_upload_token_request(self):
        handler = self.make_handler()

        handler.handle_error_message({
            "data": {
                "request_id": "request-1",
                "code": "printer_out_of_paper",
                "message": "Printer cannot accept a new task",
            }
        })

        handler.upload_token_error_callback.assert_called_once_with(
            "printer_out_of_paper",
            "Printer cannot accept a new task",
        )

    def test_unrelated_error_does_not_complete_upload_token_request(self):
        handler = self.make_handler()

        handler.handle_error_message({
            "data": {
                "request_id": "request-2",
                "code": "printer_out_of_paper",
                "message": "Printer cannot accept a new task",
            }
        })

        handler.upload_token_error_callback.assert_not_called()


class PrinterStatusSnapshotReportingTests(unittest.TestCase):
    def test_build_status_payload_preserves_vertical_runtime_state(self):
        printer_manager = Mock()
        printer_manager.get_printer_status_detail.return_value = {
            "printer_status": "printer_out_of_paper",
            "source_observed_at": "2026-07-19T01:02:03+00:00",
        }
        reporter = PrinterStatusReporter(None, printer_manager, "node-1", None)

        payload = reporter._build_status_payload(
            {"id": "local-printer", "cloud_id": "cloud-printer", "name": "HP"}
        )

        self.assertEqual("cloud-printer", payload["printer_id"])
        self.assertEqual("printer_out_of_paper", payload["printer_status"])
        self.assertEqual(
            "2026-07-19T01:02:03+00:00", payload["source_observed_at"]
        )
        self.assertEqual(
            {"printer_id", "printer_status", "source_observed_at"},
            set(payload),
        )

    def test_requested_refresh_is_coalesced_and_runs_on_reporter_thread(self):
        config = Mock()
        config.get_managed_printers.return_value = [
            {"id": "local", "cloud_id": "cloud", "name": "HP"}
        ]
        manager = Mock()
        manager.config = config
        manager.get_printer_status_detail.return_value = {
            "printer_status": "idle",
        }
        api = Mock()
        api.batch_update_printer_status.return_value = {"success": True}
        reporter = PrinterStatusReporter(None, manager, "node", api)
        reporter.check_interval = 3600
        reporter.start()
        try:
            deadline = time.time() + 1
            while (
                api.batch_update_printer_status.call_count < 1
                and time.time() < deadline
            ):
                time.sleep(0.01)
            baseline = api.batch_update_printer_status.call_count
            reporter.force_report_printer(printer_id="cloud")
            reporter.force_report_printer(printer_id="cloud")
            deadline = time.time() + 1
            while (
                api.batch_update_printer_status.call_count < baseline + 1
                and time.time() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(
                baseline + 1, api.batch_update_printer_status.call_count
            )
        finally:
            reporter.stop()
        self.assertFalse(reporter.running)
        self.assertIsNone(reporter.thread)

    def test_critical_refresh_can_wait_for_cloud_status_update(self):
        config = Mock()
        config.get_managed_printers.return_value = [
            {"id": "local", "cloud_id": "cloud", "name": "HP"}
        ]
        manager = Mock()
        manager.config = config
        manager.get_printer_status_detail.return_value = {"printer_status": "idle"}
        api = Mock()
        api.batch_update_printer_status.return_value = {"success": True}
        reporter = PrinterStatusReporter(None, manager, "node", api)
        reporter.check_interval = 3600
        reporter.start()
        try:
            self.assertTrue(
                reporter.force_report_printer(
                    printer_id="cloud",
                    wait=True,
                    timeout=1.0,
                )
            )
        finally:
            reporter.stop()


if __name__ == "__main__":
    unittest.main()
