import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from file_manager import FileManager
from portable_temp import cleanup_temp_dir


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

    def test_preview_cache_is_thread_safe_lru_with_entry_and_byte_limits(self):
        manager = FileManager(preview_max_entries=2, preview_max_bytes=10)
        manager.put_preview("first", {"preview_url": "1234"})
        manager.put_preview("second", {"preview_url": "5678"})
        self.assertIsNotNone(manager.get_preview("first"))
        manager.put_preview("third", {"preview_url": "90"})
        self.assertIsNone(manager.get_preview("second"))

        threads = [
            threading.Thread(target=manager.put_preview, args=(f"key-{index}", {"preview_url": "x"}))
            for index in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        stats = manager.get_statistics()
        self.assertLessEqual(stats["preview_entries"], 2)
        self.assertLessEqual(stats["preview_bytes"], 10)

    def test_release_download_artifact_removes_empty_job_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "portable_temp._PORTABLE_TEMP_DIR", tmpdir
        ):
            job_dir = Path(tmpdir) / "downloads" / "job-1"
            job_dir.mkdir(parents=True)
            source = job_dir / "document.pdf"
            source.write_bytes(b"pdf")
            manager = FileManager()
            manager.register_print_artifact("job-1", str(source))
            self.assertTrue(manager.release_print_artifact("job-1", reason="test"))
            self.assertFalse(job_dir.exists())

    def test_periodic_temp_cleanup_preserves_managed_cache_and_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "portable_temp._PORTABLE_TEMP_DIR", tmpdir
        ):
            root = Path(tmpdir)
            stale_files = [
                root / "preview-source.bin",
                root / "downloads" / "job" / "source.pdf",
                root / "ipp-printing" / "jobs" / "job.pdf",
            ]
            preserved = [
                root / "ipp-printing" / "document-cache" / "canonical.pdf",
                root / "ipp-printing" / "libreoffice-profile" / "registrymodifications.xcu",
            ]
            old = time.time() - 25 * 3600
            for path in stale_files + preserved:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
                os.utime(path, (old, old))
            cleanup_temp_dir(max_age_hours=24)
            self.assertTrue(all(not path.exists() for path in stale_files))
            self.assertTrue(all(path.exists() for path in preserved))


if __name__ == "__main__":
    unittest.main()
