import http.server
import struct
import tempfile
import threading
import unittest
from pathlib import Path

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


def response_bytes(request_id, *attributes):
    return (
        b"\x02\x00\x00\x00"
        + struct.pack(">I", request_id)
        + bytes([GROUP_JOB])
        + b"".join(attributes)
        + bytes([GROUP_END])
    )


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
        self.assertEqual(
            "ipp://192.0.2.2:631/ipp/print",
            validate_ipp_uri("ipp://192.0.2.2:631/ipp/print"),
        )
        for invalid in (
            "ipps://192.0.2.2/ipp/print",
            "ipp://192.0.2.2",
            "http://192.0.2.2/ipp/print",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(IppUriError):
                validate_ipp_uri(invalid)

    def test_parser_keeps_repeated_attribute_values(self):
        payload = response_bytes(
            9,
            encode_attribute(TAG_INTEGER, "job-id", 3),
            encode_attribute(TAG_INTEGER, "", 4),
        )
        response = parse_response(payload)
        self.assertEqual([3, 4], response.values("job-id"))

    def test_parser_rejects_missing_end_tag_and_trailing_bytes(self):
        without_end = response_bytes(
            9, encode_attribute(TAG_INTEGER, "job-id", 3)
        )[:-1]
        self.assertIn(
            "missing the end-of-attributes", parse_response(without_end).parse_error
        )
        self.assertIn(
            "unexpected bytes", parse_response(response_bytes(9) + b"extra").parse_error
        )

    def test_print_job_streams_pdf_with_explicit_content_length(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _IppHandler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = Path(tmp) / "test.pdf"
                pdf.write_bytes(b"%PDF-1.7\nstreamed-document")
                client = IppClient(
                    f"ipp://127.0.0.1:{server.server_port}/ipp/print"
                )
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


if __name__ == "__main__":
    unittest.main()
