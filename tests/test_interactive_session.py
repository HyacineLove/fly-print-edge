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
        self.assertTrue(self.manager.revert_print_submission(session["session_id"], "file-1"))
        self.assertTrue(self.manager.mark_print_submitted(session["session_id"], "file-1"))


if __name__ == "__main__":
    unittest.main()
