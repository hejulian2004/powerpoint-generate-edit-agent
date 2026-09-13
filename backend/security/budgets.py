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


MAX_PDF_PAGE_POINTS = 8192  # PDF page geometry limit in points
MAX_PDF_RASTER_PIXELS_PER_DIMENSION = 8192
MAX_PDF_RASTER_PIXELS_PER_PAGE = 20_000_000
MAX_PDF_RASTER_PIXELS_TOTAL = 80_000_000


def get_pdf_page_count(data: bytes) -> int:
    """Canonical PDF page count using pypdfium2. Fail-closed: raises PayloadTooLarge if unopenable."""
    if not data:
        raise PayloadTooLarge("PDF_EMPTY", "PDF 内容为空")
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(io.BytesIO(data))
        try:
            return len(doc)
        finally:
            closer = getattr(doc, "close", None)
            if callable(closer):
                closer()
    except Exception as exc:
        raise PayloadTooLarge(
            "PDF_CORRUPT_OR_UNREADABLE",
            f"无法解析 PDF 文档以确认页数预算: {exc}",
        ) from exc


def validate_pdf_page_budget(page_count: int) -> None:
    s = _get_settings()
    limit = int(getattr(s, "max_pdf_pages", 80))
    if not isinstance(page_count, int) or page_count <= 0:
        raise PayloadTooLarge(
            "PDF_INVALID_PAGE_COUNT", "PDF 页数无效，拒绝处理"
        )
    if page_count > limit:
        raise PayloadTooLarge(
            "PDF_TOO_MANY_PAGES",
            f"PDF 共 {page_count} 页，超过上限 {limit} 页",
        )


def validate_pdf_geometry_and_raster_budget(
    page_w_pt: float,
    page_h_pt: float,
    dpi: int,
    cumulative_pixels: int = 0,
) -> tuple[int, int, int]:
    """Validates geometry points and calculated raster pixel budgets fail-closed.

    Returns:
        (raster_w, raster_h, new_cumulative_pixels)
    """
    # 1. Point geometry bounds
    if (
        page_w_pt <= 0
        or page_h_pt <= 0
        or page_w_pt > MAX_PDF_PAGE_POINTS
        or page_h_pt > MAX_PDF_PAGE_POINTS
    ):
        raise PayloadTooLarge(
            "PDF_PAGE_POINTS_OUT_OF_BOUNDS",
            f"PDF 页面几何尺寸 ({page_w_pt:.1f}pt, {page_h_pt:.1f}pt) 超过上限 {MAX_PDF_PAGE_POINTS}pt",
        )

    # 2. Calculated raster pixel bounds
    scale = float(dpi) / 72.0
    raster_w = int(round(page_w_pt * scale))
    raster_h = int(round(page_h_pt * scale))

    if (
        raster_w > MAX_PDF_RASTER_PIXELS_PER_DIMENSION
        or raster_h > MAX_PDF_RASTER_PIXELS_PER_DIMENSION
    ):
        raise PayloadTooLarge(
            "PDF_PAGE_DIMENSION_PIXELS_TOO_LARGE",
            f"PDF 栅格化单边像素 ({raster_w}px, {raster_h}px) 超过上限 {MAX_PDF_RASTER_PIXELS_PER_DIMENSION}px",
        )

    page_pixels = raster_w * raster_h
    if page_pixels > MAX_PDF_RASTER_PIXELS_PER_PAGE:
        raise PayloadTooLarge(
            "PDF_PAGE_PIXELS_TOO_LARGE",
            f"PDF 页面栅格化像素 {page_pixels} 超过单页上限 {MAX_PDF_RASTER_PIXELS_PER_PAGE}",
        )

    new_cumulative = cumulative_pixels + page_pixels
    if new_cumulative > MAX_PDF_RASTER_PIXELS_TOTAL:
        raise PayloadTooLarge(
            "PDF_TOTAL_RASTER_PIXELS_EXCEEDED",
            f"PDF 累计栅格化像素 {new_cumulative} 超过总上限 {MAX_PDF_RASTER_PIXELS_TOTAL}",
        )

    return raster_w, raster_h, new_cumulative


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
    "validate_pdf_geometry_and_raster_budget",
    "VisionWorkLimiter",
    "MAX_PDF_PAGE_POINTS",
    "MAX_PDF_RASTER_PIXELS_PER_DIMENSION",
    "MAX_PDF_RASTER_PIXELS_PER_PAGE",
    "MAX_PDF_RASTER_PIXELS_TOTAL",
]
