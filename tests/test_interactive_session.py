import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interactive_session import InteractiveSessionManager


class InteractiveSessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = InteractiveSessionManager()

    def test_preview_event_binds_once_to_active_session(self):
        session = self.manager.start_session(upload_token="token-1")

        accepted = self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file-1.pdf",
            "file_name": "resume.pdf",
        })

        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["session_id"], session["session_id"])

        rejected = self.manager.accept_preview_event({
            "file_id": "file-2",
            "file_url": "https://example.com/file-2.pdf",
            "file_name": "other.pdf",
        })

        self.assertIsNone(rejected)

    def test_print_submission_is_idempotent_per_session(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file-1.pdf",
        })

        self.assertTrue(self.manager.mark_print_submitted(session["session_id"], "file-1"))
        self.assertTrue(self.manager.revert_print_submission(session["session_id"], "file-1"))
        self.assertTrue(self.manager.mark_print_submitted(session["session_id"], "file-1"))
        self.assertFalse(self.manager.mark_print_submitted(session["session_id"], "file-1"))

    def test_job_status_only_passes_for_bound_cloud_job(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file-1.pdf",
        })
        self.manager.mark_print_submitted(session["session_id"], "file-1")

        bound = self.manager.attach_cloud_job("https://example.com/file-1.pdf", "job-1")
        self.assertIsNotNone(bound)
        self.assertEqual(bound["session_id"], session["session_id"])

        accepted = self.manager.accept_job_status_event({
            "job_id": "job-1",
            "status": "completed",
            "progress": 100,
        })
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["session_id"], session["session_id"])

        rejected = self.manager.accept_job_status_event({
            "job_id": "job-2",
            "status": "completed",
            "progress": 100,
        })
        self.assertIsNone(rejected)

    def test_failed_submission_can_reopen_session(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file-1.pdf",
        })

        self.assertTrue(self.manager.mark_print_submitted(session["session_id"], "file-1"))

    def test_bound_cloud_job_keeps_authoritative_interactive_print_options(self):
        session = self.manager.start_session(upload_token="token-1")
        file_url = "https://example.com/file-1.png"
        self.manager.accept_preview_event({"file_id": "file-1", "file_url": file_url})
        options = {"paper_size": "A4", "scale_mode": "actual", "color_mode": "mono"}
        self.manager.mark_print_submitted(session["session_id"], "file-1", options)

        bound = self.manager.attach_cloud_job(file_url, "job-1")

        self.assertEqual(options, bound["print_options"])

    def test_build_snapshot_returns_idle_payload_without_active_session(self):
        self.assertEqual(
            {
                "active": False,
                "session_id": None,
                "state": "idle",
                "file_id": None,
                "file_url": None,
                "file_name": None,
                "file_type": None,
                "job_id": None,
                "submitted": False,
                "error_code": None,
                "error_message": None,
                "printer_fault": None,
                "job_status": None,
                "job_message": None,
                "current_page": None,
                "total_pages": None,
            },
            self.manager.build_snapshot(),
        )

    def test_build_snapshot_includes_bound_file_metadata(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file-1.pdf",
            "file_name": "resume.pdf",
            "file_type": "application/pdf",
        })

        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "preview_ready",
                "file_id": "file-1",
                "file_url": "https://example.com/file-1.pdf",
                "file_name": "resume.pdf",
                "file_type": "application/pdf",
                "job_id": None,
                "submitted": False,
                "error_code": None,
                "error_message": None,
                "printer_fault": None,
                "job_status": None,
                "job_message": None,
                "current_page": None,
                "total_pages": None,
            },
            self.manager.build_snapshot(),
        )

    def test_snapshot_preserves_live_ipp_stage_and_page_counts(self):
        session = self.manager.start_session(upload_token="token-1")
        file_url = "https://example.com/file-1.pdf"
        self.manager.accept_preview_event({"file_id": "file-1", "file_url": file_url})
        self.manager.mark_print_submitted(session["session_id"], "file-1")
        self.manager.attach_cloud_job(file_url, "job-1")

        self.manager.accept_job_status_event({
            "job_id": "job-1",
            "status": "printing",
            "message": "打印机正在打印……",
            "current_page": 2,
            "total_pages": 5,
        })

        snapshot = self.manager.build_snapshot()
        self.assertEqual("printing", snapshot["job_status"])
        self.assertEqual("打印机正在打印……", snapshot["job_message"])
        self.assertEqual(2, snapshot["current_page"])
        self.assertEqual(5, snapshot["total_pages"])

    def test_canceled_and_unconfirmed_are_terminal_failures(self):
        for status in ("canceled", "unconfirmed"):
            with self.subTest(status=status):
                manager = InteractiveSessionManager()
                session = manager.start_session(upload_token="token-1")
                file_url = "https://example.com/file-1.pdf"
                manager.accept_preview_event({"file_id": "file-1", "file_url": file_url})
                manager.mark_print_submitted(session["session_id"], "file-1")
                manager.attach_cloud_job(file_url, "job-1")
                manager.accept_job_status_event({"job_id": "job-1", "status": status})
                self.assertEqual("failed", manager.build_snapshot()["state"])


if __name__ == "__main__":
    unittest.main()
