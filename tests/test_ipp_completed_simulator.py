import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

from printing.ipp_protocol import IppClient, TAG_INTEGER
from tests.ipp_completed_simulator import CompletedIppHandler


class CompletedIppSimulatorTests(unittest.TestCase):
    def test_print_job_reaches_completed(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), CompletedIppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = IppClient(f"ipp://127.0.0.1:{server.server_port}/ipp/print")
            printer = client.get_printer_attributes(["printer-state", "operations-supported"])
            self.assertEqual(3, printer.first("printer-state"))
            with tempfile.TemporaryDirectory() as temp:
                pdf = Path(temp) / "test.pdf"
                pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
                submitted = client.print_pdf(pdf, "demo", "demo.pdf", [(TAG_INTEGER, "copies", 1)])
            completed = client.get_job_attributes(submitted.first("job-id"), ["job-state", "job-state-reasons"])
            self.assertEqual(9, completed.first("job-state"))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
