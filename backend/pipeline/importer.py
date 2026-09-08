"""PPTX Importer: Parses OOXML presentation decks into standard PresentationIR."""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, Union, Tuple
from ..ir.models import PresentationIR
from ..ir.converter import import_pptx

logger = logging.getLogger("backend.pipeline.importer")


class PPTImporter:
    """Handles parsing and ingestion of PPTX decks into presentation IR workspaces."""

    @classmethod
    def load_presentation(
        cls,
        input_path: Optional[Union[str, Path]] = None,
        target_slide_num: Optional[int] = None
    ) -> Tuple[PresentationIR, Optional[str], Optional[str]]:
        """Loads existing PPTX or creates a blank workspace.

        Returns: (presentation, resolved_input_path_str, error_message)
        """
        in_path_str: Optional[str] = None
        if input_path:
            in_p = Path(input_path)
            in_path_str = str(in_p)
            if not in_p.exists():
                logger.error(f"Input PPTX does not exist: {in_path_str}")
                return PresentationIR(title="Untitled"), in_path_str, f"输入文件不存在: {in_path_str}"
            try:
                pres = import_pptx(in_p)
                logger.info(f"Loaded existing presentation '{pres.title}' with {len(pres.slides)} slides from {in_path_str}")
            except Exception as e:
                logger.error(f"Failed to import input PPTX {in_path_str}: {e}")
                return PresentationIR(title="Untitled"), in_path_str, f"Failed to import input PPTX: {str(e)}"
        else:
            pres = PresentationIR(title="Untitled Presentation")
            logger.info("Initializing new PresentationIR workspace")

        # Configure active target slide
        if target_slide_num is not None and 1 <= target_slide_num <= len(pres.slides):
            pres.active_slide_id = pres.slides[target_slide_num - 1].id
        elif pres.slides and not pres.active_slide_id:
            pres.active_slide_id = pres.slides[0].id

        return pres, in_path_str, None
