"""Test-only IPP/2.0 printer that completes every accepted PDF job."""

from __future__ import annotations

import argparse
import http.server
import struct
import threading

from printing.ipp_protocol import (
    GROUP_END,
    GROUP_JOB,
    GROUP_PRINTER,
    OP_CANCEL_JOB,
    OP_GET_JOB_ATTRIBUTES,
    OP_GET_PRINTER_ATTRIBUTES,
    OP_PRINT_JOB,
    TAG_BOOLEAN,
    TAG_ENUM,
    TAG_INTEGER,
    TAG_KEYWORD,
    TAG_MIME,
    TAG_NAME,
    TAG_RANGE,
    TAG_URI,
    encode_attribute,
    encode_values,
)


def _response(request_id: int, group: int, attributes: bytes) -> bytes:
    return b"\x02\x00\x00\x00" + struct.pack(">I", request_id) + bytes([group]) + attributes + bytes([GROUP_END])


class CompletedIppHandler(http.server.BaseHTTPRequestHandler):
    job_count = 0
    lock = threading.Lock()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if len(body) < 8:
            self.send_error(400)
            return
        operation = int.from_bytes(body[2:4], "big")
        request_id = int.from_bytes(body[4:8], "big")
        if operation == OP_GET_PRINTER_ATTRIBUTES:
            attributes = b"".join((
                encode_attribute(TAG_URI, "printer-uri-supported", f"ipp://127.0.0.1:{self.server.server_port}/ipp/print"),
                encode_attribute(TAG_NAME, "printer-name", "FlyPrint Completed Simulator"),
                encode_attribute(TAG_ENUM, "printer-state", 3),
                encode_attribute(TAG_KEYWORD, "printer-state-reasons", "none"),
                encode_attribute(TAG_BOOLEAN, "printer-is-accepting-jobs", True),
                encode_values(TAG_ENUM, "operations-supported", [OP_PRINT_JOB, OP_CANCEL_JOB, OP_GET_JOB_ATTRIBUTES, OP_GET_PRINTER_ATTRIBUTES]),
                encode_attribute(TAG_MIME, "document-format-supported", "application/pdf"),
                encode_attribute(TAG_RANGE, "copies-supported", struct.pack(">ii", 1, 99)),
                encode_values(TAG_KEYWORD, "sides-supported", ["one-sided", "two-sided-long-edge"]),
                encode_attribute(TAG_KEYWORD, "media-supported", "iso_a4_210x297mm"),
                encode_attribute(TAG_BOOLEAN, "color-supported", True),
            ))
            payload = _response(request_id, GROUP_PRINTER, attributes)
        elif operation == OP_PRINT_JOB:
            with type(self).lock:
                type(self).job_count += 1
                job_id = type(self).job_count
            attributes = encode_attribute(TAG_INTEGER, "job-id", job_id) + encode_attribute(TAG_URI, "job-uri", f"ipp://simulator/ipp/print/job-{job_id}")
            payload = _response(request_id, GROUP_JOB, attributes)
        elif operation == OP_GET_JOB_ATTRIBUTES:
            attributes = b"".join((
                encode_attribute(TAG_INTEGER, "job-id", 1),
                encode_attribute(TAG_ENUM, "job-state", 9),
                encode_attribute(TAG_KEYWORD, "job-state-reasons", "job-completed-successfully"),
                encode_attribute(TAG_INTEGER, "job-impressions-completed", 1),
            ))
            payload = _response(request_id, GROUP_JOB, attributes)
        elif operation == OP_CANCEL_JOB:
            payload = _response(request_id, GROUP_JOB, encode_attribute(TAG_ENUM, "job-state", 7))
        else:
            payload = b"\x02\x00\x05\x01" + struct.pack(">I", request_id) + bytes([GROUP_END])
        self.send_response(200)
        self.send_header("Content-Type", "application/ipp")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8631)
    args = parser.parse_args()
    server = http.server.ThreadingHTTPServer((args.host, args.port), CompletedIppHandler)
    print(f"ipp://{args.host}:{server.server_port}/ipp/print", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
