import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cloud_websocket_client import PrintJobHandler


VALID_HASH = "a" * 64


class DummyConfig:
    def get_printer_by_id(self, printer_id):
        return {"id": printer_id, "name": "Production Queue"}

    def get_printer_by_name(self, name):
        return {"id": "p1", "name": name}


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()


class CloudPrintAdapterTests(unittest.TestCase):
    def make_handler(self):
        handler = PrintJobHandler(
            api_client=Mock(node_id="node"),
            printer_manager=DummyPrinterManager(),
            websocket_client=Mock(),
        )
        handler.websocket_client._begin_job_processing.return_value = "new"
        handler.websocket_client._is_job_completed.return_value = False
        return handler

    def message(self):
        return {"data": {
            "job_id": "job-1", "printer_id": "p1", "printer_name": "Production Queue",
            "file_url": "https://example.invalid/file.pdf", "content_hash": VALID_HASH,
            "name": "invoice.pdf", "print_options": {"copies": 1},
        }}

    def test_invalid_hash_is_rejected_before_download(self):
        handler = self.make_handler()
        message = self.message()
        message["data"]["content_hash"] = "invalid"
        with patch.object(handler, "_download_print_file") as download, patch.object(handler, "_report_job_failure") as failure:
            handler.handle_print_job(message)
        download.assert_not_called()
        failure.assert_called_once()

    def test_valid_job_enters_only_direct_ipp_service_adapter(self):
        handler = self.make_handler()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "invoice.pdf"
            source.write_bytes(b"%PDF")
            with patch("cloud_websocket_client.get_file_manager", return_value=None), patch.object(
                handler, "_download_print_file", return_value=str(source)
            ), patch.object(handler, "_start_ipp_print_service") as start, patch.object(
                handler.printer_manager, "submit_print_job_with_cleanup", create=True
            ) as legacy:
                handler.handle_print_job(self.message())
        start.assert_called_once()
        legacy.assert_not_called()

    def test_interactive_options_override_incomplete_cloud_echo(self):
        handler = self.make_handler()
        handler.interactive_job_binder = Mock(return_value={
            "session_id": "session-1",
            "print_options": {"scale_mode": "actual", "paper_size": "A4"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "invoice.pdf"
            source.write_bytes(b"%PDF")
            with patch("cloud_websocket_client.get_file_manager", return_value=None), patch.object(
                handler, "_download_print_file", return_value=str(source)
            ), patch.object(handler, "_start_ipp_print_service") as start:
                handler.handle_print_job(self.message())

        self.assertEqual("actual", start.call_args.kwargs["print_options"]["scale_mode"])


if __name__ == "__main__":
    unittest.main()
