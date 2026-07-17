import os
import tempfile
import time
import unittest

from file_manager import FileManager


class FileManagerCleanupTests(unittest.TestCase):
    def test_release_preview_resource_only_removes_session_caches(self):
        preview_cache = {
            'file-1:{"page_index": 0}': {"preview_url": "data", "timestamp": time.time()}
        }
        manager = FileManager(preview_cache=preview_cache)

        self.assertTrue(manager.release_preview_resource("file-1", reason="print"))
        self.assertEqual({}, preview_cache)

    def test_expired_preview_entries_are_removed(self):
        preview_cache = {
            'file-1:{"page_index": 0}': {"preview_url": "data", "timestamp": 0.0}
        }
        manager = FileManager(file_ttl=1, preview_cache=preview_cache)
        manager.cleanup_expired_files()
        self.assertEqual({}, preview_cache)

    def test_consume_and_expire_file_access_tokens(self):
        manager = FileManager()
        manager.store_file_access_token("file-1", "token-1", "2099-01-01T00:00:00Z")
        self.assertEqual("token-1", manager.consume_file_access_token("file-1"))
        self.assertIsNone(manager.consume_file_access_token("file-1"))
        manager.store_file_access_token("file-2", "token-2", "2000-01-01T00:00:00Z")
        manager.cleanup_expired_tokens()
        self.assertIsNone(manager.consume_file_access_token("file-2"))

    def test_release_print_artifact_removes_source_and_converted_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = os.path.join(tmpdir, "print.bin")
            converted = os.path.join(tmpdir, "print.pdf")
            open(source, "wb").close()
            open(converted, "wb").close()
            manager = FileManager()
            manager.register_print_artifact("job-1", source, converted)
            self.assertTrue(manager.release_print_artifact("job-1", reason="test"))
            self.assertFalse(os.path.exists(source))
            self.assertFalse(os.path.exists(converted))


if __name__ == "__main__":
    unittest.main()
