import unittest

from cloud_websocket_client import PrintJobHandler


class _FakeWebSocket:
    def __init__(self):
        self.cloud_messages = []
        self.local_messages = []

    def send_message_sync(self, message):
        self.cloud_messages.append(message)

    def dispatch_local_message(self, message_type, message):
        self.local_messages.append((message_type, message))


class _FakeApiClient:
    node_id = "node-1"


class EdgeJobStatusReportingTests(unittest.TestCase):
    def test_page_counts_are_local_only_while_cloud_receives_status(self):
        handler = PrintJobHandler.__new__(PrintJobHandler)
        handler.api_client = _FakeApiClient()
        handler.websocket_client = _FakeWebSocket()

        handler._report_job_status(
            "job-1",
            "printing",
            0,
            "打印机正在打印……",
            current_page=2,
            total_pages=5,
        )

        cloud_data = handler.websocket_client.cloud_messages[0]["data"]
        self.assertEqual("printing", cloud_data["status"])
        self.assertNotIn("current_page", cloud_data)
        self.assertNotIn("total_pages", cloud_data)

        _, local_message = handler.websocket_client.local_messages[0]
        local_data = local_message["data"]
        self.assertEqual(2, local_data["current_page"])
        self.assertEqual(5, local_data["total_pages"])


if __name__ == "__main__":
    unittest.main()
