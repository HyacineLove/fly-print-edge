from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Optional

import fitz
from PIL import Image

from libreoffice_converter import convert_document_to_pdf
from print_layout import PAPER_SIZES_MM, image_size_inches, normalize_paper_size
from .domain import ErrorCode, PreparedDocument, PrintError, PrintRequest


PDF_EXTENSIONS = {".pdf"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
IMAGE_CONVERSION_VERSION = "physical-size-v2"


class DocumentPreparer:
    def __init__(self, libreoffice_path: str, cache_dir: Path, work_dir: Path, logger=None):
        self.libreoffice_path = str(libreoffice_path or "")
        self.cache_dir = Path(cache_dir)
        self.work_dir = Path(work_dir)
        self.logger = logger or logging.getLogger(__name__)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def prepare(self, request: PrintRequest) -> PreparedDocument:
        source = Path(request.source_path)
        if not source.is_file():
            raise PrintError(ErrorCode.SOURCE_NOT_FOUND, f"source does not exist: {source}")
        source_pdf, cache_hit = self._to_pdf(source, request.content_hash)
        print_pdf = self.work_dir / f"{request.unique_document_name}.pdf"
        try:
            page_count = self._layout_pdf(source_pdf, print_pdf, request)
        except PrintError:
            raise
        except Exception as exc:
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, str(exc)) from exc
        return PreparedDocument(source_pdf, print_pdf, page_count, cache_hit)

    def _to_pdf(self, source: Path, content_hash: Optional[str]) -> tuple[Path, bool]:
        ext = source.suffix.lower()
        if ext in PDF_EXTENSIONS:
            self._validate_pdf(source)
            return source, False
        digest = content_hash or self._sha256(source)
        cache_suffix = f"-{IMAGE_CONVERSION_VERSION}" if ext in IMAGE_EXTENSIONS else ""
        cached = self.cache_dir / f"{digest}{cache_suffix}.pdf"
        if cached.is_file() and cached.stat().st_size > 0:
            self._validate_pdf(cached)
            return cached, True
        temporary = self.cache_dir / f".{digest}-{os.getpid()}.pdf"
        temporary.unlink(missing_ok=True)
        if ext in DOCUMENT_EXTENSIONS:
            if not self.libreoffice_path:
                raise PrintError(ErrorCode.CONFIG_INCOMPLETE, "LibreOffice path is not configured")
            conversion_dir = Path(tempfile.mkdtemp(prefix="flyprint-convert-", dir=self.work_dir))
            try:
                converted, error = convert_document_to_pdf(self.libreoffice_path, str(source), str(conversion_dir), logger=self.logger)
                if not converted:
                    raise PrintError(ErrorCode.DOCUMENT_CONVERSION_FAILED, error or "conversion failed")
                shutil.copy2(converted, temporary)
            finally:
                shutil.rmtree(conversion_dir, ignore_errors=True)
        elif ext in IMAGE_EXTENSIONS:
            self._image_to_pdf(source, temporary)
        else:
            raise PrintError(ErrorCode.DOCUMENT_UNSUPPORTED, f"unsupported extension: {ext}")
        self._validate_pdf(temporary)
        os.replace(temporary, cached)
        return cached, False

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_pdf(path: Path) -> None:
        try:
            with fitz.open(path) as document:
                if document.page_count < 1:
                    raise ValueError("PDF has no pages")
        except Exception as exc:
            raise PrintError(ErrorCode.DOCUMENT_PREPARATION_FAILED, f"invalid PDF {path}: {exc}") from exc

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
    def _layout_pdf(source: Path, output: Path, request: PrintRequest) -> int:
        paper_name = normalize_paper_size(request.options.paper_size)
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
                if request.options.scale_mode == "fill":
                    scale = min(max(sx, sy), request.options.max_upscale)
                elif request.options.scale_mode == "actual":
                    scale = min(1.0, sx, sy)
                else:
                    scale = min(min(sx, sy), request.options.max_upscale)
                width, height = source_rect.width * scale, source_rect.height * scale
                rect = fitz.Rect((target_w - width) / 2, (target_h - height) / 2, (target_w + width) / 2, (target_h + height) / 2)
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
