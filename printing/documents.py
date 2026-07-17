from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from typing import Callable, Optional

import fitz
from PIL import Image

from libreoffice_converter import convert_document_to_pdf
from print_layout import PAPER_SIZES_MM, image_size_inches, normalize_paper_size
from .domain import ErrorCode, PreparedDocument, PrintError, PrintOptions, PrintRequest


PDF_EXTENSIONS = {".pdf"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
PDF_CONVERSION_VERSION = "pdf-v1"
DOCUMENT_CONVERSION_VERSION = "libreoffice-v2"
IMAGE_CONVERSION_VERSION = "image-v3"
CACHE_SCHEMA_VERSION = 2
PROFILE_WARMUP_VERSION = 1


@dataclass(frozen=True)
class DocumentIdentity:
    content_hash: str
    source_name: str
    source_kind: str = ""


@dataclass(frozen=True)
class CanonicalDocument:
    cache_key: str
    pdf_path: Path
    page_count: int


@dataclass(frozen=True)
class PreviewPage:
    image: Image.Image
    page_count: int
    page_index: int


class DocumentPipeline:
    """The single boundary for source ingestion, canonical PDFs, previews and print PDFs."""

    def __init__(
        self,
        libreoffice_path: str,
        cache_dir: Path,
        work_dir: Path,
        profile_dir: Path,
        logger=None,
        *,
        cache_ttl_seconds: float = 1800.0,
        cleanup_interval_seconds: float = 300.0,
    ):
        self.libreoffice_path = str(libreoffice_path or "")
        self.cache_dir = Path(cache_dir)
        self.work_dir = Path(work_dir)
        self.profile_dir = Path(profile_dir)
        self.logger = logger or logging.getLogger(__name__)
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.cleanup_interval_seconds = float(cleanup_interval_seconds)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._guard = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._leases: dict[str, int] = {}
        self._stop_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._warmup_thread: Optional[threading.Thread] = None
        self._initialize_cache_schema()

    def start(self) -> None:
        if not self._cleanup_thread or not self._cleanup_thread.is_alive():
            self._stop_event.clear()
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                name="document-cache-cleanup",
                daemon=True,
            )
            self._cleanup_thread.start()
        self.start_libreoffice_warmup()

    def stop(self) -> None:
        self._stop_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2.0)

    def start_libreoffice_warmup(self) -> bool:
        if not self.libreoffice_path or not Path(self.libreoffice_path).is_file():
            self.logger.info("LibreOffice warmup skipped: executable is not configured")
            return False
        if self._profile_marker_matches():
            self.logger.info("LibreOffice warmup skipped: profile is ready")
            return False
        with self._guard:
            if self._warmup_thread and self._warmup_thread.is_alive():
                return False
            self._warmup_thread = threading.Thread(
                target=self._run_libreoffice_warmup,
                name="libreoffice-warmup",
                daemon=True,
            )
            self._warmup_thread.start()
        return True

    def resolve_canonical(
        self,
        identity: DocumentIdentity,
        source_supplier: Callable[[], Path],
        *,
        delete_source: bool = True,
    ) -> CanonicalDocument:
        started_at = time.perf_counter()
        self._validate_content_hash(identity.content_hash)
        extension, version = self._resolve_kind(identity)
        cache_key = f"{identity.content_hash}-{version}"
        cached = self.cache_dir / f"{cache_key}.pdf"
        lock = self._lock_for(cache_key)
        with lock:
            if cached.is_file():
                try:
                    page_count = self._validate_pdf(cached)
                except PrintError:
                    cached.unlink(missing_ok=True)
                else:
                    self._touch(cached)
                    self.logger.info(
                        "canonical_pdf_ready source=%s cache_key=%s cache_hit=true total_ms=%.1f",
                        identity.source_name,
                        cache_key,
                        (time.perf_counter() - started_at) * 1000,
                    )
                    return CanonicalDocument(cache_key, cached, page_count)

            source: Optional[Path] = None
            standardized = False
            temporary = self.cache_dir / f".{cache_key}-{uuid.uuid4().hex}.pdf"
            try:
                try:
                    source = Path(source_supplier())
                except PrintError:
                    raise
                except Exception as exc:
                    raise PrintError(ErrorCode.SOURCE_NOT_FOUND, str(exc)) from exc
                if not source.is_file():
                    raise PrintError(ErrorCode.SOURCE_NOT_FOUND, f"source does not exist: {source}")
                actual_hash = self._sha256(source)
                if actual_hash != identity.content_hash:
                    raise PrintError(
                        ErrorCode.DOCUMENT_PREPARATION_FAILED,
                        f"content hash mismatch: expected={identity.content_hash} actual={actual_hash}",
                    )
                if extension in PDF_EXTENSIONS:
                    shutil.copy2(source, temporary)
                elif extension in DOCUMENT_EXTENSIONS:
                    self._office_to_pdf(source, temporary)
                elif extension in IMAGE_EXTENSIONS:
                    self._image_to_pdf(source, temporary)
                else:
                    raise PrintError(ErrorCode.DOCUMENT_UNSUPPORTED, f"unsupported extension: {extension}")
                page_count = self._validate_pdf(temporary)
                os.replace(temporary, cached)
                standardized = True
                if extension in DOCUMENT_EXTENSIONS:
                    self._write_profile_marker()
                self._touch(cached)
                self.logger.info(
                    "canonical_pdf_ready source=%s cache_key=%s cache_hit=false pages=%s total_ms=%.1f output=%s",
                    identity.source_name,
                    cache_key,
                    page_count,
                    (time.perf_counter() - started_at) * 1000,
                    cached,
                )
                return CanonicalDocument(cache_key, cached, page_count)
            finally:
                temporary.unlink(missing_ok=True)
                if standardized and delete_source and source:
                    source.unlink(missing_ok=True)

    def prepare(self, request: PrintRequest) -> PreparedDocument:
        if not request.content_hash:
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, "content_hash is required")
        identity = DocumentIdentity(request.content_hash, request.source_name, request.source_kind)
        if request.source_supplier:
            supplier = request.source_supplier
        elif request.source_path:
            supplier = lambda: Path(request.source_path)
        else:
            raise PrintError(ErrorCode.SOURCE_NOT_FOUND, "source supplier is missing")
        canonical = self.resolve_canonical(
            identity,
            supplier,
            delete_source=request.delete_source_after_standardize,
        )
        return self.prepare_print(canonical, request.options, request.unique_document_name)

    def prepare_print(
        self,
        canonical: CanonicalDocument,
        options: PrintOptions,
        document_name: str,
    ) -> PreparedDocument:
        started_at = time.perf_counter()
        print_pdf = self.work_dir / f"{document_name}.pdf"
        with self.lease(canonical):
            page_count = self._layout_pdf(canonical.pdf_path, print_pdf, options)
        self.logger.info(
            "document_prepare_finished cache_key=%s pages=%s layout_ms=%.1f",
            canonical.cache_key,
            page_count,
            (time.perf_counter() - started_at) * 1000,
        )
        return PreparedDocument(canonical.pdf_path, print_pdf, page_count, True)

    def render_preview(
        self,
        canonical: CanonicalDocument,
        options: PrintOptions,
        page_index: int,
    ) -> PreviewPage:
        preview_pdf = self.work_dir / f"preview-{uuid.uuid4().hex}.pdf"
        try:
            with self.lease(canonical):
                page_count = self._layout_pdf(canonical.pdf_path, preview_pdf, options)
            resolved = max(0, min(int(page_index), page_count - 1))
            with fitz.open(preview_pdf) as document:
                page = document.load_page(resolved)
                pixmap = page.get_pixmap(dpi=120, alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            if options.color_mode == "mono":
                image = image.convert("L").convert("RGB")
            return PreviewPage(image, page_count, resolved)
        except PrintError:
            raise
        except Exception as exc:
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, str(exc)) from exc
        finally:
            preview_pdf.unlink(missing_ok=True)

    @contextmanager
    def lease(self, canonical: CanonicalDocument):
        with self._guard:
            self._leases[canonical.cache_key] = self._leases.get(canonical.cache_key, 0) + 1
        try:
            self._touch(canonical.pdf_path)
            yield canonical.pdf_path
        finally:
            self._touch(canonical.pdf_path)
            with self._guard:
                remaining = self._leases.get(canonical.cache_key, 1) - 1
                if remaining > 0:
                    self._leases[canonical.cache_key] = remaining
                else:
                    self._leases.pop(canonical.cache_key, None)

    def cleanup_expired(self, now: Optional[float] = None) -> int:
        current = time.time() if now is None else float(now)
        removed = 0
        for path in self.cache_dir.glob("*.pdf"):
            cache_key = path.stem
            with self._guard:
                active = self._leases.get(cache_key, 0) > 0
            if active:
                continue
            try:
                if current - path.stat().st_mtime > self.cache_ttl_seconds:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        if removed:
            self.logger.info("Canonical PDF cache cleanup removed=%s", removed)
        return removed

    def _office_to_pdf(self, source: Path, output: Path) -> None:
        if not self.libreoffice_path:
            raise PrintError(ErrorCode.CONFIG_INCOMPLETE, "LibreOffice path is not configured")
        conversion_dir = Path(tempfile.mkdtemp(prefix="flyprint-convert-", dir=self.work_dir))
        try:
            converted, error = convert_document_to_pdf(
                self.libreoffice_path,
                str(source),
                str(conversion_dir),
                str(self.profile_dir),
                logger=self.logger,
            )
            if not converted:
                raise PrintError(ErrorCode.DOCUMENT_CONVERSION_FAILED, error or "conversion failed")
            shutil.copy2(converted, output)
        finally:
            shutil.rmtree(conversion_dir, ignore_errors=True)

    @staticmethod
    def _image_to_pdf(source: Path, output: Path) -> None:
        document = fitz.open()
        try:
            with Image.open(source) as image:
                while True:
                    frame = image.copy()
                    if image.info.get("dpi") and not frame.info.get("dpi"):
                        frame.info["dpi"] = image.info["dpi"]
                    width_in, height_in = image_size_inches(frame)
                    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buffer:
                        frame.convert("RGB").save(buffer, format="PNG")
                        buffer.seek(0)
                        page = document.new_page(width=width_in * 72, height=height_in * 72)
                        page.insert_image(page.rect, stream=buffer.read())
                    try:
                        image.seek(image.tell() + 1)
                    except EOFError:
                        break
            document.save(output, garbage=4, deflate=True)
        finally:
            document.close()

    @staticmethod
    def _layout_pdf(source: Path, output: Path, options: PrintOptions) -> int:
        paper_name = normalize_paper_size(options.paper_size)
        size_mm = PAPER_SIZES_MM.get(paper_name)
        if not size_mm:
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, f"unsupported paper: {paper_name}")
        target_w, target_h = size_mm[0] * 72 / 25.4, size_mm[1] * 72 / 25.4
        source_doc = fitz.open(source)
        target_doc = fitz.open()
        try:
            for page_number, source_page in enumerate(source_doc):
                page = target_doc.new_page(width=target_w, height=target_h)
                source_rect = source_page.rect
                sx, sy = target_w / source_rect.width, target_h / source_rect.height
                if options.scale_mode == "fill":
                    scale = min(max(sx, sy), options.max_upscale)
                elif options.scale_mode == "actual":
                    scale = min(1.0, sx, sy)
                else:
                    scale = min(min(sx, sy), options.max_upscale)
                width, height = source_rect.width * scale, source_rect.height * scale
                rect = fitz.Rect(
                    (target_w - width) / 2,
                    (target_h - height) / 2,
                    (target_w + width) / 2,
                    (target_h + height) / 2,
                )
                page.show_pdf_page(rect, source_doc, page_number, keep_proportion=True)
            output.unlink(missing_ok=True)
            target_doc.save(output, garbage=4, deflate=True)
            return target_doc.page_count
        finally:
            target_doc.close()
            source_doc.close()

    @staticmethod
    def cleanup(prepared: PreparedDocument) -> None:
        prepared.print_pdf.unlink(missing_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_content_hash(value: str) -> None:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, "invalid content_hash")

    @staticmethod
    def _validate_pdf(path: Path) -> int:
        try:
            with fitz.open(path) as document:
                if document.page_count < 1:
                    raise ValueError("PDF has no pages")
                return document.page_count
        except Exception as exc:
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, f"invalid PDF {path}: {exc}") from exc

    @staticmethod
    def _touch(path: Path) -> None:
        try:
            os.utime(path, None)
        except FileNotFoundError:
            pass

    def _resolve_kind(self, identity: DocumentIdentity) -> tuple[str, str]:
        extension = Path(identity.source_name).suffix.lower()
        kind = (identity.source_kind or "").lower()
        if not extension:
            mime_extensions = {
                "application/pdf": ".pdf",
                "application/msword": ".doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.oasis.opendocument.text": ".odt",
                "application/rtf": ".rtf",
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/bmp": ".bmp",
                "image/gif": ".gif",
                "image/tiff": ".tiff",
                "image/webp": ".webp",
            }
            extension = mime_extensions.get(kind, "")
        if extension in PDF_EXTENSIONS:
            return extension, PDF_CONVERSION_VERSION
        if extension in DOCUMENT_EXTENSIONS:
            return extension, DOCUMENT_CONVERSION_VERSION
        if extension in IMAGE_EXTENSIONS:
            return extension, IMAGE_CONVERSION_VERSION
        raise PrintError(ErrorCode.DOCUMENT_UNSUPPORTED, f"unsupported source kind: {identity.source_name!r} {identity.source_kind!r}")

    def _lock_for(self, cache_key: str) -> threading.Lock:
        with self._guard:
            return self._key_locks.setdefault(cache_key, threading.Lock())

    def _cleanup_loop(self) -> None:
        while not self._stop_event.wait(self.cleanup_interval_seconds):
            try:
                self.cleanup_expired()
            except Exception:
                self.logger.exception("Canonical PDF cache cleanup failed")

    def _initialize_cache_schema(self) -> None:
        marker = self.cache_dir / ".schema-version"
        current = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if current != str(CACHE_SCHEMA_VERSION):
            for path in self.cache_dir.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
            marker.write_text(str(CACHE_SCHEMA_VERSION), encoding="utf-8")

    def _profile_fingerprint(self) -> dict[str, object]:
        executable = Path(self.libreoffice_path).resolve()
        stat = executable.stat()
        return {
            "warmup_version": PROFILE_WARMUP_VERSION,
            "executable": str(executable).lower(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    @property
    def _profile_marker_path(self) -> Path:
        return self.profile_dir / ".flyprint-profile-ready.json"

    def _profile_marker_matches(self) -> bool:
        try:
            stored = json.loads(self._profile_marker_path.read_text(encoding="utf-8"))
            return stored == self._profile_fingerprint()
        except Exception:
            return False

    def _write_profile_marker(self) -> None:
        marker = self._profile_marker_path
        temporary = marker.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(self._profile_fingerprint(), sort_keys=True), encoding="utf-8")
        os.replace(temporary, marker)

    def _run_libreoffice_warmup(self) -> None:
        started_at = time.perf_counter()
        warmup_dir = Path(tempfile.mkdtemp(prefix="libreoffice-warmup-", dir=self.work_dir))
        source = warmup_dir / "flyprint-warmup.docx"
        try:
            self._write_minimal_docx(source)
            converted, error = convert_document_to_pdf(
                self.libreoffice_path,
                str(source),
                str(warmup_dir),
                str(self.profile_dir),
                logger=self.logger,
            )
            if not converted:
                raise RuntimeError(error or "warmup conversion failed")
            self._validate_pdf(Path(converted))
            self._write_profile_marker()
            self.logger.info(
                "LibreOffice warmup finished: elapsed_ms=%.1f",
                (time.perf_counter() - started_at) * 1000,
            )
        except Exception:
            self.logger.exception("LibreOffice warmup failed")
        finally:
            shutil.rmtree(warmup_dir, ignore_errors=True)

    @staticmethod
    def _write_minimal_docx(path: Path) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>",
            )
            archive.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                "</Relationships>",
            )
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>FlyPrint LibreOffice warmup</w:t></w:r></w:p><w:sectPr/></w:body>'
                "</w:document>",
            )
