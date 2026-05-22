import os
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_manager import FileManager


class FileManagerCleanupTests(unittest.TestCase):
    def test_release_preview_resource_removes_files_and_related_caches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "preview.bin")
            pdf_path = os.path.join(tmpdir, "preview.pdf")
            with open(source_path, "wb") as fh:
                fh.write(b"preview")
            with open(pdf_path, "wb") as fh:
                fh.write(b"pdf")

            preview_cache = {
                'file-1:{"page_index": 0}': {"preview_url": "data:image/png;base64,xxx", "timestamp": 1.0}
            }
            preview_page_cache = {"file-1": {0: object()}}
            preview_page_meta = {"file-1": {"page_count": 1}}

            manager = FileManager(
                cleanup_interval=300,
                file_ttl=1800,
                preview_cache=preview_cache,
                preview_page_cache=preview_page_cache,
                preview_page_meta=preview_page_meta,
            )
            manager.register_preview_resource("file-1", "url-1", source_path, pdf_path)

            released = manager.release_preview_resource("file-1", reason="test")

            self.assertTrue(released)
            self.assertFalse(os.path.exists(source_path))
            self.assertFalse(os.path.exists(pdf_path))
            self.assertEqual({}, preview_cache)
            self.assertEqual({}, preview_page_cache)
            self.assertEqual({}, preview_page_meta)

    def test_consume_and_expire_file_access_tokens(self):
        manager = FileManager(cleanup_interval=300, file_ttl=1800)
        manager.store_file_access_token("file-1", "token-1", "2099-01-01T00:00:00Z")
        consumed = manager.consume_file_access_token("file-1")
        self.assertEqual("token-1", consumed)
        self.assertIsNone(manager.consume_file_access_token("file-1"))

        manager.store_file_access_token("file-2", "token-2", "2000-01-01T00:00:00Z")
        manager.cleanup_expired_tokens()
        self.assertIsNone(manager.consume_file_access_token("file-2"))

    def test_release_print_artifact_removes_source_and_converted_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "print.bin")
            converted_path = os.path.join(tmpdir, "print.pdf")
            with open(source_path, "wb") as fh:
                fh.write(b"print")
            with open(converted_path, "wb") as fh:
                fh.write(b"pdf")

            manager = FileManager(cleanup_interval=300, file_ttl=1800)
            manager.register_print_artifact("job-1", source_path, converted_path)
            released = manager.release_print_artifact("job-1", reason="test")

            self.assertTrue(released)
            self.assertFalse(os.path.exists(source_path))
            self.assertFalse(os.path.exists(converted_path))


if __name__ == "__main__":
    unittest.main()
