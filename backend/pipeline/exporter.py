"""Pipeline Exporter: PPT-IR to standard OOXML .pptx serialization and schema validation."""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Union, Tuple, Optional
from ..ir.models import PresentationIR
from ..ir.converter import export_pptx
from pptx_agent_converter.validation import validate_pptx

logger = logging.getLogger("backend.pipeline.exporter")


class PPTExporter:
    """Serializes PresentationIR to standard OOXML .pptx packages and verifies structural validity."""

    @classmethod
    def export_and_validate(
        cls,
        pres: PresentationIR,
        output_path: Union[str, Path]
    ) -> Tuple[bool, bool, Optional[str]]:
        """Exports to OOXML and runs schema integrity validation.

        Returns: (export_success, validation_valid, error_message)
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        try:
            export_pptx(pres, out_p)
        except Exception as e:
            logger.error(f"Failed to export PPTX to {out_p}: {e}")
            return False, False, f"Failed to export PPTX: {str(e)}"

        try:
            val_res = validate_pptx(out_p)
            is_valid = bool(val_res.get("valid", False))
            return True, is_valid, None
        except Exception as e:
            logger.warning(f"Validation inspection error: {e}")
            return True, False, f"Validation error: {str(e)}"
