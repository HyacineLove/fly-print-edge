import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main
import print_runtime


class RuntimeResourceLimitTests(unittest.TestCase):
    def test_sse_queue_drops_oldest_and_keeps_latest_event(self):
        queue = asyncio.Queue(maxsize=2)
        main._enqueue_sse_latest(queue, {"sequence": 1})
        main._enqueue_sse_latest(queue, {"sequence": 2})
        main._enqueue_sse_latest(queue, {"sequence": 3})
        self.assertEqual(2, queue.qsize())
        self.assertEqual({"sequence": 2}, queue.get_nowait())
        self.assertEqual({"sequence": 3}, queue.get_nowait())

    def test_pipeline_factory_starts_new_instance_and_stops_replaced_instance(self):
        instances = []

        class FakePipeline:
            def __init__(self, *args, **kwargs):
                self.started = False
                self.stopped = False
                instances.append(self)

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

        config = Mock()
        config.get_full_config.return_value = {"settings": {"libreoffice_path": "first.exe"}}
        with tempfile.TemporaryDirectory() as tmp, patch(
            "portable_temp._PORTABLE_TEMP_DIR", tmp
        ), patch("print_runtime.DocumentPipeline", FakePipeline):
            print_runtime.stop_document_pipelines()
            first = print_runtime.build_document_pipeline(config, Mock())
            self.assertTrue(first.started)
            config.get_full_config.return_value = {"settings": {"libreoffice_path": "second.exe"}}
            second = print_runtime.build_document_pipeline(config, Mock())
            self.assertTrue(first.stopped)
            self.assertTrue(second.started)
            print_runtime.stop_document_pipelines()
            self.assertTrue(second.stopped)


if __name__ == "__main__":
    unittest.main()
