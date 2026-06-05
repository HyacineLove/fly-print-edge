import io
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_fault_probe import (
    IPPPrinterFaultProbe,
    build_ipp_get_printer_attributes_request,
    parse_ipp_response,
    resolve_printer_host,
)


def ipp_attr(name: str, value, tag: int) -> bytes:
    name_bytes = name.encode("utf-8")
    if isinstance(value, bool):
        value_bytes = b"\x01" if value else b"\x00"
    elif isinstance(value, int):
        value_bytes = int(value).to_bytes(4, "big", signed=True)
    else:
        value_bytes = str(value).encode("utf-8")
    return (
        bytes([tag])
        + len(name_bytes).to_bytes(2, "big")
        + name_bytes
        + len(value_bytes).to_bytes(2, "big")
        + value_bytes
    )


def ipp_response(state: int, reasons: list[str], accepting: bool = True) -> bytes:
    body = b"\x02\x00\x00\x00\x00\x00\x00\x01\x04"
    body += ipp_attr("printer-state", state, 0x23)
    first = True
    for reason in reasons:
        body += ipp_attr("printer-state-reasons" if first else "", reason, 0x44)
        first = False
    body += ipp_attr("printer-is-accepting-jobs", accepting, 0x22)
    body += b"\x03"
    return body


class PrinterFaultProbeTests(unittest.TestCase):
    def test_resolve_printer_host_from_location_url(self):
        printer = {"location": "http://169.254.12.234:3911"}

        self.assertEqual("169.254.12.234", resolve_printer_host(printer))

    def test_resolve_printer_host_from_plain_ip_port(self):
        printer = {"location": "169.254.12.234:3911"}

        self.assertEqual("169.254.12.234", resolve_printer_host(printer))

    def test_parse_ipp_response_reads_state_reasons_and_accepting_jobs(self):
        parsed = parse_ipp_response(
            ipp_response(5, ["media-empty-error", "media-needed-error"], accepting=True)
        )

        self.assertEqual([5], parsed["attributes"]["printer-state"])
        self.assertEqual(
            ["media-empty-error", "media-needed-error"],
            parsed["attributes"]["printer-state-reasons"],
        )
        self.assertEqual([True], parsed["attributes"]["printer-is-accepting-jobs"])

    def test_probe_reports_fault_for_stopped_media_error(self):
        response = io.BytesIO(
            ipp_response(5, ["media-empty-error", "media-needed-error"], accepting=True)
        )

        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = response.read()
            result = IPPPrinterFaultProbe(timeout=1).probe("169.254.12.234")

        self.assertTrue(result.available)
        self.assertTrue(result.faulted)
        self.assertEqual(5, result.printer_state)
        self.assertEqual("stopped", result.printer_state_name)
        self.assertEqual(["media-empty-error", "media-needed-error"], result.fault_reasons)

    def test_probe_does_not_report_fault_for_idle_none(self):
        response = io.BytesIO(ipp_response(3, ["none"], accepting=True))

        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = response.read()
            result = IPPPrinterFaultProbe(timeout=1).probe("169.254.12.234")

        self.assertTrue(result.available)
        self.assertFalse(result.faulted)
        self.assertEqual("idle", result.printer_state_name)
        self.assertEqual([], result.fault_reasons)

    def test_probe_unavailable_when_request_fails(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = IPPPrinterFaultProbe(timeout=1).probe("169.254.12.234")

        self.assertFalse(result.available)
        self.assertFalse(result.faulted)
        self.assertIn("timed out", result.error)

    def test_build_request_uses_ipp_print_endpoint(self):
        request = build_ipp_get_printer_attributes_request("169.254.12.234")

        self.assertEqual("http://169.254.12.234:631/ipp/print", request.full_url)
        self.assertEqual("POST", request.get_method())
        self.assertEqual("application/ipp", request.headers["Content-type"])


if __name__ == "__main__":
    unittest.main()
