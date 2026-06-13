import os
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_manager import FileManager


class FileManagerCleanupTests(unittest.TestCase):
    CONTENT_HASH = "a" * 64
    OTHER_FILE_HASH = "b" * 64

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

    def test_hash_resource_survives_single_file_release_until_all_references_expire(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "shared.bin")
            with open(source_path, "wb") as fh:
                fh.write(b"shared")

            manager = FileManager(cleanup_interval=300, file_ttl=1800)
            manager.register_preview_resource(
                "file-1",
                "url-1",
                source_path,
                content_hash=self.CONTENT_HASH,
            )
            reused = manager.reuse_cached_resource(
                "file-2",
                "url-2",
                self.CONTENT_HASH,
            )

            self.assertIsNotNone(reused)
            self.assertEqual(source_path, reused["source_path"])

            manager.release_preview_resource("file-1", reason="cancel")
            self.assertTrue(os.path.exists(source_path))

            manager.release_preview_resource("file-2", reason="cancel")
            self.assertFalse(os.path.exists(source_path))

    def test_print_release_only_clears_file_reference_and_preview_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "preview.bin")
            with open(source_path, "wb") as fh:
                fh.write(b"preview")

            preview_cache = {
                'file-1:{"page_index": 0}': {"preview_url": "data:image/png;base64,xxx", "timestamp": 1.0}
            }
            manager = FileManager(
                cleanup_interval=300,
                file_ttl=1800,
                preview_cache=preview_cache,
            )
            manager.register_preview_resource(
                "file-1",
                "url-1",
                source_path,
                content_hash=self.CONTENT_HASH,
            )

            released = manager.release_preview_resource("file-1", reason="print")

            self.assertTrue(released)
            self.assertTrue(os.path.exists(source_path))
            self.assertEqual({}, preview_cache)
            self.assertEqual(source_path, manager.get_cached_path(self.CONTENT_HASH))

    def test_expired_hash_resource_removes_source_after_ttl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "preview.bin")
            with open(source_path, "wb") as fh:
                fh.write(b"preview")

            manager = FileManager(cleanup_interval=300, file_ttl=1)
            manager.register_preview_resource(
                "file-1",
                "url-1",
                source_path,
                content_hash=self.CONTENT_HASH,
            )

            with manager.preview_lock:
                manager.preview_files["file-1"]["last_access"] = 0
                manager.hash_resources[self.CONTENT_HASH]["last_access"] = 0

            manager.cleanup_expired_files()

            self.assertFalse(os.path.exists(source_path))
            self.assertIsNone(manager.get_cached_path(self.CONTENT_HASH))

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

    def test_release_print_artifact_preserves_shared_cache_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "shared.bin")
            converted_path = os.path.join(tmpdir, "converted.pdf")
            with open(source_path, "wb") as fh:
                fh.write(b"shared")
            with open(converted_path, "wb") as fh:
                fh.write(b"pdf")

            manager = FileManager(cleanup_interval=300, file_ttl=1800)
            manager.register_print_artifact(
                "job-1",
                source_path,
                converted_path,
                owns_source=False,
            )
            released = manager.release_print_artifact("job-1", reason="test")

            self.assertTrue(released)
            self.assertTrue(os.path.exists(source_path))
            self.assertFalse(os.path.exists(converted_path))


if __name__ == "__main__":
    unittest.main()
