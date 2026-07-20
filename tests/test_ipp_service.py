import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from printing.domain import (
    ErrorCode,
    IppJobRef,
    PrintError,
    PrintOptions,
    PrintRequest,
    PrintState,
)
from printing.service import DeviceJobRegistry, IppPrintService


class IppServiceStateTests(unittest.TestCase):
    def setUp(self):
        self.service = IppPrintService(Mock(), poll_seconds=0.0, timeout_seconds=1.0)
        self.request = PrintRequest(
            job_id="job-1",
            printer_name="Printer",
            printer_uuid="urn:uuid:p1",
            ipp_uri="ipp://192.0.2.2:631/ipp/print",
            source_path=Path("input.pdf"),
            source_name="input.pdf",
            options=PrintOptions(),
        )
        self.ref = IppJobRef(
            self.request.ipp_uri,
            self.request.printer_uuid,
            42,
            "ipp://printer/jobs/42",
            "FlyPrint-job-1",
        )

    def test_completed_job_wins_over_later_printer_fault(self):
        with (
            patch("printing.service.job_snapshot", return_value={"job-state": [9]}),
            patch(
                "printing.service.printer_snapshot",
                return_value={"printer-state-reasons": ["media-empty-error"]},
            ),
        ):
            event = self.service._monitor(
                self.request, 1, self.ref, Mock(), threading.Event(), None
            )
        self.assertEqual(PrintState.COMPLETED, event.state)

    def test_monitor_emits_device_completed_pages(self):
        request = PrintRequest(
            job_id="job-2",
            printer_name="Printer",
            printer_uuid="urn:uuid:p1",
            ipp_uri="ipp://192.0.2.2:631/ipp/print",
            source_path=Path("input.pdf"),
            source_name="input.pdf",
            options=PrintOptions(duplex="longedge"),
        )
        events = []
        jobs = [
            {
                "job-state": [5],
                "job-state-reasons": ["job-printing"],
                "job-impressions-completed": [2],
            },
            {"job-state": [9]},
        ]
        with (
            patch("printing.service.job_snapshot", side_effect=jobs),
            patch(
                "printing.service.printer_snapshot",
                return_value={"printer-state-reasons": ["none"]},
            ),
        ):
            event = self.service._monitor(
                request, 4, self.ref, Mock(), threading.Event(), events.append
            )

        self.assertEqual(2, events[0].current_page)
        self.assertEqual(4, events[0].total_pages)
        self.assertEqual(4, event.current_page)
        self.assertEqual(4, event.total_pages)

    def test_active_fault_is_canceled_and_reported_as_original_fault(self):
        jobs = [
            {"job-state": [5], "job-state-reasons": ["job-printing"]},
            {"job-state": [7], "job-state-reasons": ["job-canceled-by-operator"]},
        ]
        with (
            patch("printing.service.job_snapshot", side_effect=jobs),
            patch(
                "printing.service.printer_snapshot",
                return_value={"printer-state-reasons": ["media-empty-error"]},
            ),
            patch.object(self.service, "_send_cancel") as cancel,
        ):
            with self.assertRaises(PrintError) as raised:
                self.service._monitor(
                    self.request, 1, self.ref, Mock(), threading.Event(), None
                )
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_PAPER, raised.exception.code)
        cancel.assert_called_once_with(unittest.mock.ANY, 42)

    def test_job_query_failure_is_unconfirmed(self):
        with patch(
            "printing.service.job_snapshot", side_effect=RuntimeError("connection lost")
        ):
            with self.assertRaises(PrintError) as raised:
                self.service._monitor(
                    self.request, 1, self.ref, Mock(), threading.Event(), None
                )
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


if __name__ == "__main__":
    unittest.main()
