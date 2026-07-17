import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cloud_websocket_client import CloudWebSocketClient, PrintJobHandler
from file_manager import FileManager


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

    @staticmethod
    def download_response(chunks):
        response = Mock(status_code=200)
        response.iter_content.return_value = iter(chunks)
        return response

    def test_same_filename_downloads_are_streamed_into_distinct_job_directories(self):
        handler = self.make_handler()
        manager = FileManager()
        responses = [self.download_response([b"first"]), self.download_response([b"second"])]
        with tempfile.TemporaryDirectory() as tmp, patch(
            "portable_temp._PORTABLE_TEMP_DIR", tmp
        ), patch("cloud_websocket_client.get_file_manager", return_value=manager), patch(
            "cloud_websocket_client.requests.get", side_effect=responses
        ) as request_get:
            first = handler._download_print_file("https://example.invalid/file.pdf", "job-1", "same.pdf")
            second = handler._download_print_file("https://example.invalid/file.pdf", "job-2", "same.pdf")

            self.assertNotEqual(Path(first).parent, Path(second).parent)
            self.assertEqual(b"first", Path(first).read_bytes())
            self.assertEqual(b"second", Path(second).read_bytes())
            self.assertTrue(all(call.kwargs["stream"] for call in request_get.call_args_list))
            self.assertEqual([], list(Path(tmp).rglob("*.part")))

    def test_failed_stream_download_removes_part_and_job_directory(self):
        handler = self.make_handler()
        manager = FileManager()
        response = self.download_response([])
        response.iter_content.side_effect = OSError("network interrupted")
        with tempfile.TemporaryDirectory() as tmp, patch(
            "portable_temp._PORTABLE_TEMP_DIR", tmp
        ), patch("cloud_websocket_client.get_file_manager", return_value=manager), patch(
            "cloud_websocket_client.requests.get", return_value=response
        ):
            result = handler._download_print_file(
                "https://example.invalid/file.pdf", "job-failed", "same.pdf"
            )
            self.assertIsNone(result)
            self.assertEqual([], list(Path(tmp).rglob("*.part")))
            self.assertEqual([], list((Path(tmp) / "downloads").glob("*")))


class CloudJobCleanupTests(unittest.TestCase):
    def test_cleanup_thread_stops_and_expired_processing_markers_are_released(self):
        client = CloudWebSocketClient("ws://example.invalid", Mock())
        client.completed_jobs["completed"] = time.time() - 7200
        client.processing_jobs["processing"] = time.time() - 7200
        client._cleanup_completed_jobs()
        self.assertEqual({}, client.completed_jobs)
        self.assertEqual({}, client.processing_jobs)
        thread = client._job_cleanup_thread
        client.stop()
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
