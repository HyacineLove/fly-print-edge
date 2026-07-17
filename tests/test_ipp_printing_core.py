import http.server
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from printing.discovery import _decode_txt, _host_for_uri
from printing.domain import ErrorCode, IppJobRef, PrintError, PrintOptions, PrintRequest, PrintState
from printing.ipp_device import IppPrinterProbe, active_job_fault, normalize_capabilities, printer_fault, validate_options
from printing.ipp_protocol import (
    GROUP_END,
    GROUP_JOB,
    IppClient,
    IppUriError,
    TAG_INTEGER,
    TAG_URI,
    encode_attribute,
    parse_response,
    validate_ipp_uri,
)
from printing.service import DeviceJobRegistry, IppPrintService


def response_bytes(request_id, *attributes):
    return b"\x02\x00\x00\x00" + struct.pack(">I", request_id) + bytes([GROUP_JOB]) + b"".join(attributes) + bytes([GROUP_END])


class _IppHandler(http.server.BaseHTTPRequestHandler):
    body = b""
    content_length = 0

    def do_POST(self):
        type(self).content_length = int(self.headers["Content-Length"])
        type(self).body = self.rfile.read(type(self).content_length)
        request_id = int.from_bytes(type(self).body[4:8], "big")
        payload = response_bytes(
            request_id,
            encode_attribute(TAG_INTEGER, "job-id", 17),
            encode_attribute(TAG_URI, "job-uri", "ipp://printer/ipp/print/job-17"),
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/ipp")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


class IppProtocolTests(unittest.TestCase):
    def test_uri_requires_plain_ipp_and_explicit_path(self):
        self.assertEqual("ipp://192.0.2.2:631/ipp/print", validate_ipp_uri("ipp://192.0.2.2:631/ipp/print"))
        for invalid in ("ipps://192.0.2.2/ipp/print", "ipp://192.0.2.2", "http://192.0.2.2/ipp/print"):
            with self.subTest(invalid=invalid), self.assertRaises(IppUriError):
                validate_ipp_uri(invalid)

    def test_parser_keeps_repeated_attribute_values(self):
        payload = response_bytes(9, encode_attribute(TAG_INTEGER, "job-id", 3), encode_attribute(TAG_INTEGER, "", 4))
        response = parse_response(payload)
        self.assertEqual([3, 4], response.values("job-id"))

    def test_parser_rejects_missing_end_tag_and_trailing_bytes(self):
        without_end = response_bytes(9, encode_attribute(TAG_INTEGER, "job-id", 3))[:-1]
        self.assertIn("missing the end-of-attributes", parse_response(without_end).parse_error)
        self.assertIn("unexpected bytes", parse_response(response_bytes(9) + b"extra").parse_error)

    def test_print_job_streams_pdf_with_explicit_content_length(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _IppHandler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = Path(tmp) / "test.pdf"
                pdf.write_bytes(b"%PDF-1.7\nstreamed-document")
                client = IppClient(f"ipp://127.0.0.1:{server.server_port}/ipp/print")
                response = client.print_pdf(
                    pdf,
                    "FlyPrint-test",
                    "test.pdf",
                    [(TAG_INTEGER, "copies", 1)],
                )
            thread.join(3)
        finally:
            server.server_close()
        self.assertEqual(17, response.first("job-id"))
        self.assertEqual(_IppHandler.content_length, len(_IppHandler.body))
        self.assertTrue(_IppHandler.body.endswith(b"%PDF-1.7\nstreamed-document"))


class IppDevicePolicyTests(unittest.TestCase):
    def capabilities(self):
        return normalize_capabilities({
            "document-format-supported": ["application/pdf"],
            "ipp-versions-supported": ["2.0"],
            "operations-supported": [2, 8, 9, 11],
            "job-creation-attributes-supported": ["copies", "sides", "print-color-mode", "media", "ipp-attribute-fidelity"],
            "copies-supported": [[1, 99]],
            "sides-supported": ["one-sided", "two-sided-long-edge", "two-sided-short-edge"],
            "print-color-mode-supported": ["monochrome", "color"],
            "media-supported": ["iso_a4_210x297mm", "na_letter_8.5x11in"],
        })

    def test_all_current_print_options_map_to_strict_ipp_attributes(self):
        attributes = validate_options(self.capabilities(), PrintOptions(2, "longedge", "color", "A4"))
        self.assertEqual(
            [(TAG_INTEGER, "copies", 2), (0x44, "sides", "two-sided-long-edge"), (0x44, "print-color-mode", "color"), (0x44, "media", "iso_a4_210x297mm")],
            attributes,
        )

    def test_printer_alert_alone_does_not_cancel_active_job(self):
        job = {"job-state": [5], "job-state-reasons": ["job-printing"], "job-impressions-completed": [1]}
        printer = {
            "printer-state-reasons": ["spool-area-full-report"],
            "printer-alert-description": ["allTraysEmpty", "outOfMedia"],
        }
        self.assertIsNone(active_job_fault(job, printer))
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_PAPER, printer_fault(printer, include_reports_and_alerts=True))

    def test_printer_error_is_attributed_to_active_job(self):
        job = {"job-state": [5], "job-state-reasons": ["job-printing"]}
        printer = {"printer-state-reasons": ["media-empty-error"]}
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_PAPER, active_job_fault(job, printer))

    def test_low_toner_does_not_block_submission(self):
        printer = {"printer-state-reasons": ["toner-low-warning"]}
        self.assertIsNone(printer_fault(printer, include_reports_and_alerts=True))

    def test_all_supported_media_names_have_explicit_mappings(self):
        expected = {
            "A3": "iso_a3_297x420mm", "A4": "iso_a4_210x297mm",
            "A5": "iso_a5_148x210mm", "B5": "iso_b5_176x250mm",
            "Letter": "na_letter_8.5x11in", "Legal": "na_legal_8.5x14in",
            "Tabloid": "na_ledger_11x17in",
        }
        for paper, media in expected.items():
            with self.subTest(paper=paper):
                self.assertEqual(media, PrintOptions(paper_size=paper).ipp_media)


class IppServiceStateTests(unittest.TestCase):
    def setUp(self):
        self.service = IppPrintService(Mock(), poll_seconds=0.0, timeout_seconds=1.0)
        self.request = PrintRequest(
            job_id="job-1", printer_name="Printer", printer_uuid="urn:uuid:p1",
            ipp_uri="ipp://192.0.2.2:631/ipp/print", source_path=Path("input.pdf"),
            source_name="input.pdf", options=PrintOptions(),
        )
        self.ref = IppJobRef(self.request.ipp_uri, self.request.printer_uuid, 42, "ipp://printer/jobs/42", "FlyPrint-job-1")

    def test_completed_job_wins_over_later_printer_fault(self):
        with patch("printing.service.job_snapshot", return_value={"job-state": [9]}), \
             patch("printing.service.printer_snapshot", return_value={"printer-state-reasons": ["media-empty-error"]}):
            event = self.service._monitor(self.request, 1, self.ref, Mock(), threading.Event(), None)
        self.assertEqual(PrintState.COMPLETED, event.state)

    def test_active_fault_is_canceled_and_reported_as_original_fault(self):
        jobs = [
            {"job-state": [5], "job-state-reasons": ["job-printing"]},
            {"job-state": [7], "job-state-reasons": ["job-canceled-by-operator"]},
        ]
        with patch("printing.service.job_snapshot", side_effect=jobs), \
             patch("printing.service.printer_snapshot", return_value={"printer-state-reasons": ["media-empty-error"]}), \
             patch.object(self.service, "_send_cancel") as cancel:
            with self.assertRaises(PrintError) as raised:
                self.service._monitor(self.request, 1, self.ref, Mock(), threading.Event(), None)
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_PAPER, raised.exception.code)
        cancel.assert_called_once_with(unittest.mock.ANY, 42)

    def test_job_query_failure_is_unconfirmed(self):
        with patch("printing.service.job_snapshot", side_effect=RuntimeError("connection lost")):
            with self.assertRaises(PrintError) as raised:
                self.service._monitor(self.request, 1, self.ref, Mock(), threading.Event(), None)
        self.assertEqual(ErrorCode.IPP_JOB_QUERY_FAILED, raised.exception.code)
        self.assertEqual(PrintState.UNCONFIRMED, raised.exception.state)

    def test_single_device_registry_rejects_concurrent_and_uncertain_jobs(self):
        registry = DeviceJobRegistry()
        first = registry.acquire("urn:uuid:p1", "job-1")
        self.assertIsNotNone(first)
        self.assertIsNone(registry.acquire("urn:uuid:p1", "job-2"))
        registry.release("urn:uuid:p1", first)
        registry.mark_uncertain("urn:uuid:p1", "lost-response")
        self.assertIsNone(registry.acquire("urn:uuid:p1", "job-3"))
        self.assertTrue(registry.clear_uncertain("urn:uuid:p1"))
        final = registry.acquire("urn:uuid:p1", "job-4")
        self.assertIsNotNone(final)
        registry.release("urn:uuid:p1", final)


class IppDiscoveryPolicyTests(unittest.TestCase):
    def test_dns_sd_txt_and_ipv6_uri_parts_are_normalized(self):
        self.assertEqual({"rp": "ipp/print", "ty": "Printer"}, _decode_txt({b"RP": b"ipp/print", b"ty": b"Printer"}))
        self.assertEqual("[fe80::1]", _host_for_uri("fe80::1"))
        self.assertEqual("192.0.2.2", _host_for_uri("192.0.2.2"))


if __name__ == "__main__":
    unittest.main()
