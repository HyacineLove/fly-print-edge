import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from printing.documents import (
    CanonicalDocument,
    DocumentIdentity,
    DocumentPipeline,
    PDF_CONVERSION_VERSION,
)
from printing.domain import PrintError, PrintOptions


def write_pdf(path: Path, pages: int = 1) -> None:
    document = fitz.open()
    try:
        for _ in range(pages):
            document.new_page(width=300, height=500)
        document.save(path)
    finally:
        document.close()


class DocumentPipelineTests(unittest.TestCase):
    def make_pipeline(self, root: Path, **kwargs) -> DocumentPipeline:
        soffice = root / "soffice.exe"
        soffice.touch(exist_ok=True)
        return DocumentPipeline(
            str(soffice),
            root / "cache",
            root / "jobs",
            root / "profile",
            cleanup_interval_seconds=0.01,
            **kwargs,
        )

    def test_pdf_is_canonicalized_then_source_deleted_and_reused_without_supplier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            write_pdf(source, 2)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            pipeline = self.make_pipeline(root)
            first = pipeline.resolve_canonical(DocumentIdentity(digest, "source.pdf"), lambda: source)
            self.assertFalse(source.exists())
            self.assertEqual(2, first.page_count)
            self.assertEqual(f"{digest}-{PDF_CONVERSION_VERSION}.pdf", first.pdf_path.name)

            def unexpected_supplier():
                raise AssertionError("supplier must not run on a canonical cache hit")

            second = pipeline.resolve_canonical(DocumentIdentity(digest, "source.pdf"), unexpected_supplier)
            self.assertEqual(first.pdf_path, second.pdf_path)

    def test_hash_mismatch_is_rejected_and_source_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            write_pdf(source)
            pipeline = self.make_pipeline(root)
            with self.assertRaises(PrintError):
                pipeline.resolve_canonical(DocumentIdentity("a" * 64, source.name), lambda: source)
            self.assertTrue(source.exists())
            self.assertEqual([], list((root / "cache").glob("*.pdf")))

    def test_image_preview_and_print_use_the_same_layout_page_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "image.png"
            Image.new("RGB", (600, 300), "red").save(source, dpi=(100, 100))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            pipeline = self.make_pipeline(root)
            canonical = pipeline.resolve_canonical(
                DocumentIdentity(digest, source.name, "image/png"), lambda: source, delete_source=False,
            )
            options = PrintOptions(paper_size="A4", scale_mode="fit", color_mode="color")
            preview = pipeline.render_preview(canonical, options, 0)
            prepared = pipeline.prepare_print(canonical, options, "job-image")
            try:
                self.assertEqual(preview.page_count, prepared.page_count)
                self.assertEqual((993, 1404), preview.image.size)
            finally:
                pipeline.cleanup(prepared)

    def test_same_key_concurrent_requests_download_and_convert_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            write_pdf(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            pipeline = self.make_pipeline(root)
            calls = 0
            calls_lock = threading.Lock()
            results = []

            def supplier():
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.03)
                return source

            def resolve():
                results.append(
                    pipeline.resolve_canonical(
                        DocumentIdentity(digest, source.name), supplier, delete_source=False,
                    )
                )

            threads = [threading.Thread(target=resolve) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(1, calls)
            self.assertEqual(1, len({item.pdf_path for item in results}))

    def test_cache_survives_pipeline_recreation_and_sliding_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            write_pdf(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            first_pipeline = self.make_pipeline(root, cache_ttl_seconds=10)
            canonical = first_pipeline.resolve_canonical(
                DocumentIdentity(digest, source.name), lambda: source, delete_source=False,
            )
            old_time = time.time() - 20
            os.utime(canonical.pdf_path, (old_time, old_time))
            second_pipeline = self.make_pipeline(root, cache_ttl_seconds=10)
            reused = second_pipeline.resolve_canonical(
                DocumentIdentity(digest, source.name), lambda: (_ for _ in ()).throw(AssertionError()),
            )
            self.assertGreater(reused.pdf_path.stat().st_mtime, old_time)
            self.assertEqual(0, second_pipeline.cleanup_expired(now=time.time()))

    def test_active_lease_prevents_expiration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            write_pdf(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            pipeline = self.make_pipeline(root, cache_ttl_seconds=1)
            canonical = pipeline.resolve_canonical(
                DocumentIdentity(digest, source.name), lambda: source, delete_source=False,
            )
            old_time = time.time() - 10
            os.utime(canonical.pdf_path, (old_time, old_time))
            with pipeline.lease(canonical):
                self.assertEqual(0, pipeline.cleanup_expired(now=time.time()))
                self.assertTrue(canonical.pdf_path.exists())

    def test_new_profile_warms_asynchronously_and_marker_skips_next_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline = self.make_pipeline(root)

            def convert(_soffice, _source, output_dir, _profile, logger=None):
                output = Path(output_dir) / "flyprint-warmup.pdf"
                write_pdf(output)
                return str(output), None

            with patch("printing.documents.convert_document_to_pdf", side_effect=convert) as converter:
                started = time.perf_counter()
                self.assertTrue(pipeline.start_libreoffice_warmup())
                self.assertLess(time.perf_counter() - started, 0.1)
                pipeline._warmup_thread.join(timeout=2)
                self.assertTrue(pipeline._profile_marker_path.is_file())
                self.assertFalse(pipeline.start_libreoffice_warmup())
                self.assertEqual(1, converter.call_count)

                executable = Path(pipeline.libreoffice_path)
                os.utime(executable, ns=(executable.stat().st_atime_ns, executable.stat().st_mtime_ns + 1_000_000))
                self.assertTrue(pipeline.start_libreoffice_warmup())
                pipeline._warmup_thread.join(timeout=2)
                self.assertEqual(2, converter.call_count)


if __name__ == "__main__":
    unittest.main()
