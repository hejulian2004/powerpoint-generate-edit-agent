"""Upload / parse / vision resource budgets (PR #28 Phase 0).

All limits are enforced BEFORE the expensive work they guard:
- file bytes are streamed in chunks (never a blind ``await file.read()``);
- OOXML zip budgets are checked from the central directory BEFORE the
  Fidelity/OOXML parser runs;
- PDF page counts are checked BEFORE full raster + vision analysis;
- vision fan-out is bounded by a global semaphore.

``Content-Length`` is only a pre-reject hint; the chunked counter is the
enforcement boundary.
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from typing import Optional

logger = logging.getLogger(__name__)


class PayloadTooLarge(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _get_settings():  # lazy to avoid import cycles
    from ..config import settings

    return settings


async def read_upload_bounded(upload, max_bytes: int, chunk_size: int = 64 * 1024) -> bytes:  # type: ignore[no-untyped-def]
    """Read an UploadFile in chunks, failing closed past ``max_bytes``."""
    total = 0
    parts: list[bytes] = []
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLarge(
                "PAYLOAD_TOO_LARGE",
                f"上传文件超过 {max_bytes} 字节上限",
            )
        parts.append(chunk)
    return b"".join(parts)


def validate_ooxml_zip_budget(data: bytes) -> None:
    """Pre-parse OOXML zip bomb / traversal guard (before import_pptx)."""
    s = _get_settings()
    max_uncompressed = int(getattr(s, "pptx_max_uncompressed_bytes", 200 * 1024 * 1024))
    max_entries = int(getattr(s, "pptx_max_entries", 1000))
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PayloadTooLarge("INVALID_OOXML_ZIP", f"不是有效的 OOXML zip 包：{exc}")
    try:
        infos = zf.infolist()
    except Exception as exc:
        raise PayloadTooLarge("INVALID_OOXML_ZIP", f"无法读取 zip 目录：{exc}")
    if len(infos) > max_entries:
        raise PayloadTooLarge(
            "OOXML_TOO_MANY_ENTRIES",
            f"PPTX 条目 {len(infos)} 超过上限 {max_entries}",
        )
    total_uncompressed = 0
    total_compressed = 0
    for info in infos:
        name = info.filename or ""
        # Zip-slip traversal.
        if ".." in name.replace("\\", "/").split("/") or name.startswith("/"):
            raise PayloadTooLarge(
                "OOXML_PATH_TRAVERSAL", f"PPTX 包含可疑路径条目：{name!r}"
            )
        # Encrypted entries cannot be safely inspected.
        if info.flag_bits & 0x1:
            raise PayloadTooLarge(
                "OOXML_ENCRYPTED", "PPTX 包含加密条目，拒绝导入"
            )
        uncompressed = int(info.file_size or 0)
        compressed = int(info.compress_size or 0)
        if uncompressed > max_uncompressed:
            raise PayloadTooLarge(
                "OOXML_ENTRY_TOO_LARGE",
                f"PPTX 单条目 {name!r} 解压后 {uncompressed} 字节超过上限",
            )
        total_uncompressed += uncompressed
        total_compressed += compressed
        if total_uncompressed > max_uncompressed:
            raise PayloadTooLarge(
                "OOXML_UNCOMPRESSED_TOO_LARGE",
                f"PPTX 累计解压 {total_uncompressed} 字节超过上限 {max_uncompressed}",
            )
    if total_compressed > 0:
        ratio = total_uncompressed / max(total_compressed, 1)
        if ratio > 100 and total_uncompressed > 10 * 1024 * 1024:
            raise PayloadTooLarge(
                "OOXML_COMPRESSION_RATIO",
                f"PPTX 解压比 {ratio:.1f}x 疑似 zip bomb，拒绝导入",
            )


def get_pdf_page_count(data: bytes) -> Optional[int]:
    """Best-effort fast page count (before raster). Returns None if unknown."""
    # Try pypdf first (pure-python, no render).
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return len(reader.pages)
    except Exception:
        pass
    try:
        import fitz  # PyMuPDF, if available

        doc = fitz.open(stream=data, filetype="pdf")
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:
        return None


def validate_pdf_page_budget(page_count: Optional[int]) -> None:
    s = _get_settings()
    limit = int(getattr(s, "max_pdf_pages", 80))
    if page_count is not None and page_count > limit:
        raise PayloadTooLarge(
            "PDF_TOO_MANY_PAGES",
            f"PDF 共 {page_count} 页，超过上限 {limit} 页",
        )


class VisionWorkLimiter:
    """Global semaphore bounding concurrent vision / raster work."""

    _semaphore: Optional[asyncio.Semaphore] = None
    _loop = None

    @classmethod
    def semaphore(cls) -> asyncio.Semaphore:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        s = _get_settings()
        limit = max(1, int(getattr(s, "vision_concurrency", 4)))
        if cls._semaphore is None or cls._loop is not loop:
            cls._semaphore = asyncio.Semaphore(limit)
            cls._loop = loop
        return cls._semaphore


__all__ = [
    "PayloadTooLarge",
    "read_upload_bounded",
    "validate_ooxml_zip_budget",
    "get_pdf_page_count",
    "validate_pdf_page_budget",
    "VisionWorkLimiter",
]
