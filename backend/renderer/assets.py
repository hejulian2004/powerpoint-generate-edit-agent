"""Asset Resolver and Synthesis Layer (PR11).

Resolves source figures and tables from PaperIR or asset directories.
Synthesizes high-fidelity academic placeholder figures and structured tables
when raster assets are not directly available on disk, ensuring robust, self-healing pipeline execution.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PIL import Image

from ..paper.schema import PaperIR, PaperTable


class AssetResolver:
    """Resolves asset identifiers (source_figure_id, source_table_id) to filesystem paths or data structures."""

    def __init__(
        self,
        paper_ir: Optional[PaperIR] = None,
        assets_dir: Optional[Union[str, Path]] = None,
        cache_dir: Optional[Union[str, Path]] = None,
    ):
        self.paper_ir = paper_ir
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self.cache_dir = (
            Path(cache_dir)
            if cache_dir
            else Path(tempfile.gettempdir()) / "opencode_asset_cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Build figure / table index from PaperIR
        self._figure_index: Dict[str, Any] = {}
        self._table_index: Dict[str, PaperTable] = {}
        if self.paper_ir:
            for fig in self.paper_ir.figures:
                self._figure_index[fig.id.lower()] = fig
            for tbl in self.paper_ir.tables:
                self._table_index[tbl.id.lower()] = tbl

    def resolve_figure(
        self,
        figure_id: str,
        caption_hint: str = "",
        width: int = 800,
        height: int = 500,
        allow_synthetic: bool = False,
    ) -> Path:
        """Resolve figure_id to an existing image file on disk.

        Raises FileNotFoundError when missing. The PPTSpec pipeline uses
        PresentationIR ShapeElementIR placeholders instead of fabricating images.
        """
        clean_id = figure_id.strip()

        # 1. Search in explicitly provided assets_dir
        if self.assets_dir and self.assets_dir.is_dir():
            direct_asset = self.assets_dir / clean_id
            if direct_asset.is_file():
                return direct_asset
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate = self.assets_dir / f"{clean_id}{ext}"
                if candidate.is_file():
                    return candidate

        # 2. Check if figure_id is an existing absolute or relative path
        direct_path = Path(clean_id)
        if direct_path.is_file():
            return direct_path

        # 3. Missing figure asset -> raise FileNotFoundError
        raise FileNotFoundError(f"Figure asset '{figure_id}' could not be resolved on disk.")

    def resolve_table(
        self,
        table_id: str,
        content_payload: Optional[Dict[str, Any]] = None,
        allow_synthetic: bool = False,
    ) -> Dict[str, Any]:
        """Resolve structured table headers and rows for a TableElement."""
        clean_id = table_id.strip().lower()
        payload = content_payload or {}

        # 1. Direct explicit data inside element payload
        if "header" in payload and "rows" in payload and payload["rows"]:
            return {
                "header": list(payload["header"]),
                "rows": [list(r) for r in payload["rows"]],
                "caption": payload.get("caption", ""),
                "xref_label": payload.get("xref_label", ""),
                "highlight_cells": payload.get("highlight_cells", []),
            }

        # 2. Check PaperIR extracted tables
        tbl_obj = self._table_index.get(clean_id)
        if tbl_obj and tbl_obj.header and tbl_obj.rows:
            return {
                "header": tbl_obj.header,
                "rows": tbl_obj.rows,
                "caption": tbl_obj.caption,
                "xref_label": tbl_obj.xref_label,
                "highlight_cells": payload.get("highlight_cells", []),
            }

        # 3. Explicit placeholder fallback without any fabricated benchmark data
        caption = payload.get("caption") or (tbl_obj.caption if tbl_obj else "")
        xref = payload.get("xref_label") or (tbl_obj.xref_label if tbl_obj else table_id)

        return {
            "header": ["Table", "Status"],
            "rows": [
                [f"[{xref.upper()}]", "Placeholder: Raw table data not provided in paper extract"],
            ],
            "caption": caption,
            "xref_label": xref,
            "highlight_cells": [],
        }
