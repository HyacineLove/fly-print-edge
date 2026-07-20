import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import main
from file_manager import FileManager
from printing.documents import CanonicalDocument, PreviewPage
from printing.domain import ErrorCode, USER_MESSAGES


class DummyConfig:
    def __init__(self):
        self.config = {
            "managed_printers": [{
                "id": "printer-1",
                "cloud_id": "cloud-printer-1",
                "name": "HP",
                "type": "ipp",
                "printer_uuid": "urn:uuid:printer-1",
                "ipp_uri": "ipp://192.168.50.2:631/ipp/print",
                "enabled": True,
            }],
            "default_printer_id": "printer-1",
            "cloud": {"node_id": "node-123"},
            "settings": {"copies_min": 1, "copies_max": 3},
            "network": {"bind_address": "127.0.0.1", "port": 7860},
        }

    def get_full_config(self):
        return self.config

    def get_default_printer_id(self):
        return self.config.get("default_printer_id")

    def set_default_printer_id(self, printer_id):
        self.config["default_printer_id"] = printer_id

    def clear_default_printer_id(self):
        self.config["default_printer_id"] = None

    def get_managed_printers(self):
        return self.config["managed_printers"]


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()

    def get_printers(self):
        return self.config.get_managed_printers()

    def get_printer_capabilities(self, printer_name):
        return {"page_size": ["A4"], "color_model": ["RGB"], "duplex": ["None"]}


class DummyWebSocketClient:
    def __init__(self):
        self.sent_messages = []
        self.upload_token_requested = False
        self.requested_printer_id = None

    async def send_message(self, message):
        self.sent_messages.append(message)
        return True

    def request_upload_token(self, node_id, printer_id, request_id=""):
        self.upload_token_requested = True
        self.requested_printer_id = printer_id
        return False


class DummyStatusReporter:
    def force_report_printer(self, printer_id=None, printer_name=None, **kwargs):
        return True


class DummyCloudService:
    def __init__(self):
        self.node_id = "node-123"
        self.websocket_client = DummyWebSocketClient()
        self.print_job_handler = None
        self.status_reporter = DummyStatusReporter()


class DummyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class DummyBodyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def body(self):
        return json.dumps(self.payload).encode("utf-8")


class UserPreviewPrintApiTests(unittest.TestCase):
    CONTENT_HASH = "a" * 64

    def setUp(self):
        self.printer_manager = DummyPrinterManager()
        self.cloud_service = DummyCloudService()
        self.session_manager = main.InteractiveSessionManager()
        self.temp_dir = tempfile.TemporaryDirectory()
        session = self.session_manager.start_session(upload_token="upload-token")
        self.session_id = session["session_id"]
        self.session_manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file.pdf",
            "content_hash": self.CONTENT_HASH,
        })
        self.file_manager = FileManager(cleanup_interval=300, file_ttl=1800)

    def tearDown(self):
        self.temp_dir.cleanup()
        main.preview_cache = {}

    def _print_request(self, copies):
        return DummyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "options": {"copies": copies, "duplex": "simplex", "color_mode": "color"},
        })

    def _submit(self, request, file_manager=None):
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "_ensure_default_printer", return_value="printer-1"), \
             patch.object(main, "get_file_manager", return_value=file_manager):
            return asyncio.run(main.submit_print(request))

    def test_submit_print_clamps_copies_and_uses_cloud_printer_id(self):
        response = self._submit(self._print_request(99))
        self.assertTrue(response["success"])
        data = self.cloud_service.websocket_client.sent_messages[0]["data"]
        self.assertEqual(3, data["options"]["copies"])
        self.assertEqual("cloud-printer-1", data["printer_id"])

    def test_submit_print_clamps_copies_to_configured_minimum(self):
        response = self._submit(self._print_request(0))
        self.assertTrue(response["success"])
        self.assertEqual(1, self.cloud_service.websocket_client.sent_messages[0]["data"]["options"]["copies"])

    def test_submit_print_requires_cloud_registration(self):
        self.printer_manager.config.config["managed_printers"][0]["cloud_id"] = None
        response = self._submit(self._print_request(1))
        self.assertEqual(503, response.status_code)
        self.assertEqual([], self.cloud_service.websocket_client.sent_messages)

    def test_submit_print_clears_session_preview_cache(self):
        main.preview_cache = {'file-1:{"page_index": 0}': {"preview_url": "data", "timestamp": 1.0}}
        self.file_manager = FileManager(
            cleanup_interval=300,
            file_ttl=1800,
            preview_cache=main.preview_cache,
        )
        response = self._submit(self._print_request(1), self.file_manager)
        self.assertTrue(response["success"])
        self.assertEqual({}, main.preview_cache)

    def test_preview_rejects_missing_content_hash(self):
        request = DummyBodyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "file_url": "https://example.com/file.pdf",
            "file_name": "file.pdf",
            "file_type": "application/pdf",
            "options": {"page_index": 0},
        })
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "get_file_manager", return_value=self.file_manager):
            response = asyncio.run(main.preview(request))
        self.assertEqual(400, response.status_code)
        self.assertIn("content_hash", response.body.decode("utf-8"))

    def test_preview_reuses_cached_hash_without_download(self):
        source_path = os.path.join(self.temp_dir.name, "preview.pdf")
        pipeline = Mock()
        pipeline.resolve_canonical.return_value = CanonicalDocument(self.CONTENT_HASH + "-pdf-v1", Path(source_path), 1)
        pipeline.render_preview.return_value = PreviewPage(Image.new("RGB", (10, 10)), 1, 0)
        request = DummyBodyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "file.pdf",
            "file_type": "application/pdf",
            "content_hash": self.CONTENT_HASH,
            "options": {"page_index": 0},
        })
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "build_document_pipeline", return_value=pipeline), \
             patch.object(main, "_download_preview_file") as download_mock, \
             patch.object(main, "get_file_manager", return_value=self.file_manager):
            response = asyncio.run(main.preview(request))
        self.assertTrue(response["success"])
        download_mock.assert_not_called()

    def _availability(self, reason):
        snapshot = {
            "printer-state": [5],
            "printer-state-reasons": [reason],
            "printer-is-accepting-jobs": [False],
        }
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch("printing.ipp_device.printer_snapshot", return_value=snapshot):
            return asyncio.run(main.get_printer_availability())

    def test_printer_availability_reports_ipp_paper_fault(self):
        response = self._availability("media-empty-error")
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_PAPER.value, response["reason_code"])
        self.assertEqual(USER_MESSAGES[ErrorCode.PRINTER_OUT_OF_PAPER], response["message"])

    def test_printer_availability_reports_ipp_toner_fault(self):
        response = self._availability("toner-empty-error")
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_TONER.value, response["reason_code"])

    def test_qr_code_does_not_request_token_while_printer_faulted(self):
        snapshot = {
            "printer-state": [5],
            "printer-state-reasons": ["media-empty-error"],
            "printer-is-accepting-jobs": [False],
        }
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "node_id", "node-123"), \
             patch("printing.ipp_device.printer_snapshot", return_value=snapshot):
            response = asyncio.run(main.get_qr_code())
        self.assertFalse(response["success"])
        self.assertFalse(self.cloud_service.websocket_client.upload_token_requested)

    def test_qr_code_requests_token_with_cloud_printer_id(self):
        ready = {
            "printer-state": [3],
            "printer-state-reasons": ["none"],
            "printer-is-accepting-jobs": [True],
        }
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "node_id", "node-123"), \
             patch("printing.ipp_device.printer_snapshot", return_value=ready):
            response = asyncio.run(main.get_qr_code())
        self.assertEqual(500, response.status_code)
        self.assertEqual("cloud-printer-1", self.cloud_service.websocket_client.requested_printer_id)


if __name__ == "__main__":
    unittest.main()
