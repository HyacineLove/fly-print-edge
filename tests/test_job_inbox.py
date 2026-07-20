import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from job_inbox import JobInbox


class JobInboxTests(unittest.TestCase):
    def test_duplicate_delivery_is_retained_once_and_received_job_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = JobInbox(os.path.join(directory, "inbox.sqlite3"))
            payload = {"type": "print_job", "data": {"job_id": "job-1"}}
            self.assertEqual(inbox.receive("job-1", "message-1", payload), (True, "received"))
            self.assertEqual(inbox.receive("job-1", "message-2", payload), (False, "received"))
            received, interrupted = inbox.recovery()
            self.assertEqual(received, [payload])
            self.assertEqual(interrupted, [])

    def test_processing_job_is_not_recovered_for_a_second_print(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = JobInbox(os.path.join(directory, "inbox.sqlite3"))
            inbox.receive("job-1", "message-1", {"data": {"job_id": "job-1"}})
            self.assertTrue(inbox.mark_processing("job-1"))
            received, interrupted = inbox.recovery()
            self.assertEqual(received, [])
            self.assertEqual(interrupted, ["job-1"])


if __name__ == "__main__":
    unittest.main()
