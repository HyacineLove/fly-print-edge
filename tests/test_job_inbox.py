import os
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from job_delivery_store import JobDeliveryStore
from cloud_websocket_client import CloudWebSocketClient


class JobDeliveryStoreTests(unittest.TestCase):
    def test_duplicate_delivery_is_retained_once_and_received_job_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = JobDeliveryStore(os.path.join(directory, "inbox.sqlite3"))
            payload = {"type": "print_job", "data": {"job_id": "job-1"}}
            self.assertEqual(inbox.receive("job-1", "message-1", payload), (True, "received"))
            self.assertEqual(inbox.receive("job-1", "message-2", payload), (False, "received"))
            received, interrupted = inbox.recovery()
            self.assertEqual(received, [payload])
            self.assertEqual(interrupted, [])

    def test_processing_job_is_not_recovered_for_a_second_print(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = JobDeliveryStore(os.path.join(directory, "inbox.sqlite3"))
            inbox.receive("job-1", "message-1", {"data": {"job_id": "job-1"}})
            self.assertTrue(inbox.mark_processing("job-1"))
            received, interrupted = inbox.recovery()
            self.assertEqual(received, [])
            self.assertEqual(interrupted, ["job-1"])

    def test_terminal_report_is_stable_until_cloud_accepts_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobDeliveryStore(os.path.join(directory, "delivery.sqlite3"))
            store.receive("job-1", "message-1", {"data": {"job_id": "job-1"}})
            store.mark_processing("job-1")
            first = store.record_terminal_report("job-1", "completed", {"job_id": "job-1", "status": "completed"})
            second = store.record_terminal_report("job-1", "completed", {"job_id": "job-1", "status": "completed"})
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(store.due_terminal_reports(), [first])
            store.schedule_terminal_report_retry(first["event_id"], "awaiting_cloud_ack")
            self.assertEqual(store.due_terminal_reports(), [])
            store.acknowledge_terminal_report(first["event_id"])
            self.assertEqual(store.report_summary()["pending"], 0)

    def test_cloud_rejection_remains_visible_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobDeliveryStore(os.path.join(directory, "delivery.sqlite3"))
            store.receive("job-1", "message-1", {"data": {"job_id": "job-1"}})
            report = store.record_terminal_report("job-1", "failed", {"job_id": "job-1", "status": "failed"})
            store.reject_terminal_report(report["event_id"], "job_status_conflict")
            summary = store.report_summary()
            self.assertEqual(summary["rejected"], 1)
            self.assertEqual(summary["last_rejected"]["reason"], "job_status_conflict")

    def test_cloud_ack_removes_only_the_matching_terminal_report(self):
        with tempfile.TemporaryDirectory() as directory:
            client = CloudWebSocketClient(
                "ws://example.invalid",
                Mock(),
                inbox_path=os.path.join(directory, "delivery.sqlite3"),
                node_id="node-1",
            )
            try:
                self.assertTrue(client.queue_terminal_job_update(
                    "job-1", "completed", {"job_id": "job-1", "status": "completed"}
                ))
                report = client.job_delivery_store.due_terminal_reports()[0]
                client._handle_job_update_ack({"event_id": report["event_id"], "status": "accepted"})
                self.assertEqual(client.terminal_report_summary()["pending"], 0)
            finally:
                client.stop()


if __name__ == "__main__":
    unittest.main()
