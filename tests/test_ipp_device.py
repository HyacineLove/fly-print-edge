import unittest

from printing.domain import ErrorCode, PrintOptions
from printing.ipp_device import (
    PrinterObservation,
    active_job_fault,
    normalize_capabilities,
    normalize_printer_runtime,
    printer_fault,
    validate_options,
)
from printing.ipp_protocol import TAG_INTEGER


class IppDevicePolicyTests(unittest.TestCase):
    def capabilities(self):
        return normalize_capabilities(
            {
                "document-format-supported": ["application/pdf"],
                "ipp-versions-supported": ["2.0"],
                "operations-supported": [2, 8, 9, 11],
                "job-creation-attributes-supported": [
                    "copies",
                    "sides",
                    "print-color-mode",
                    "media",
                    "ipp-attribute-fidelity",
                ],
                "copies-supported": [[1, 99]],
                "sides-supported": [
                    "one-sided",
                    "two-sided-long-edge",
                    "two-sided-short-edge",
                ],
                "print-color-mode-supported": ["monochrome", "color"],
                "media-supported": [
                    "iso_a4_210x297mm",
                    "na_letter_8.5x11in",
                ],
            }
        )

    def test_all_current_print_options_map_to_strict_ipp_attributes(self):
        attributes = validate_options(
            self.capabilities(), PrintOptions(2, "longedge", "color", "A4")
        )
        self.assertEqual(
            [
                (TAG_INTEGER, "copies", 2),
                (0x44, "sides", "two-sided-long-edge"),
                (0x44, "print-color-mode", "color"),
                (0x44, "media", "iso_a4_210x297mm"),
            ],
            attributes,
        )

    def test_printer_alert_alone_does_not_cancel_active_job(self):
        job = {"job-state": [5], "job-state-reasons": ["job-printing"]}
        printer = {
            "printer-state-reasons": ["spool-area-full-report"],
            "printer-alert-description": ["allTraysEmpty", "outOfMedia"],
        }
        self.assertIsNone(active_job_fault(job, printer))
        self.assertIsNone(printer_fault(printer))

    def test_printer_error_is_attributed_to_active_job(self):
        job = {"job-state": [5], "job-state-reasons": ["job-printing"]}
        printer = {"printer-state-reasons": ["media-empty-error"]}
        self.assertEqual(
            ErrorCode.PRINTER_OUT_OF_PAPER, active_job_fault(job, printer)
        )

    def test_low_toner_does_not_block_submission(self):
        printer = {"printer-state-reasons": ["toner-low-warning"]}
        self.assertIsNone(printer_fault(printer))

    def test_low_toner_does_not_override_runtime_status(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [3],
                    "printer-is-accepting-jobs": [True],
                    "printer-state-reasons": ["toner-low-warning"],
                }
            )
        )
        self.assertEqual("idle", runtime.printer_status)

    def test_processing_printer_may_temporarily_reject_new_jobs_without_fault(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [4],
                    "printer-is-accepting-jobs": [False],
                    "printer-state-reasons": ["none"],
                }
            )
        )
        self.assertEqual("printing", runtime.printer_status)

    def test_local_activity_does_not_override_idle_device_state(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [3],
                    "printer-is-accepting-jobs": [True],
                    "printer-state-reasons": ["none"],
                }
            )
        )
        self.assertEqual("idle", runtime.printer_status)

    def test_blocking_fault_has_priority_over_unconfirmed_lock(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [5],
                    "printer-is-accepting-jobs": [False],
                    "printer-state-reasons": ["media-empty-error"],
                },
                uncertain=True,
            )
        )
        self.assertEqual(ErrorCode.PRINTER_OUT_OF_PAPER.value, runtime.printer_status)

    def test_unconfirmed_lock_overrides_idle_device_state(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [3],
                    "printer-is-accepting-jobs": [True],
                    "printer-state-reasons": ["none"],
                },
                uncertain=True,
            )
        )
        self.assertEqual("printer_unconfirmed_lock", runtime.printer_status)

    def test_report_does_not_override_runtime_status(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [3],
                    "printer-is-accepting-jobs": [True],
                    "printer-state-reasons": ["media-empty-report"],
                }
            )
        )
        self.assertEqual("idle", runtime.printer_status)

    def test_unknown_device_state_blocks_new_jobs_with_stable_reason(self):
        runtime = normalize_printer_runtime(
            PrinterObservation(
                {
                    "printer-state": [0],
                    "printer-is-accepting-jobs": [True],
                    "printer-state-reasons": ["none"],
                }
            )
        )
        self.assertEqual("printer_state_unknown", runtime.printer_status)

    def test_all_supported_media_names_have_explicit_mappings(self):
        expected = {
            "A3": "iso_a3_297x420mm",
            "A4": "iso_a4_210x297mm",
            "A5": "iso_a5_148x210mm",
            "B5": "iso_b5_176x250mm",
            "Letter": "na_letter_8.5x11in",
            "Legal": "na_legal_8.5x14in",
            "Tabloid": "na_ledger_11x17in",
        }
        for paper, media in expected.items():
            with self.subTest(paper=paper):
                self.assertEqual(media, PrintOptions(paper_size=paper).ipp_media)


if __name__ == "__main__":
    unittest.main()
