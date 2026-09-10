"""OOXML Capability Matrix & Detection.

Defines the features the Fidelity Engine can parse/edit and which OOXML features it can
only detect (present in the package but not editable). This is the single source of truth
the Agent uses to answer "can I modify that?" before attempting a mutation.

Engine support boundary (FidelityCapability defaults):
- Fully supported: shape, text, image, group, table, theme
- Detect-only (parsed into IR if possible, but edits are NOT safe):
  chart, smartart, animation, master_slide
"""

from __future__ import annotations
import io
import os
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Union

from ..ir.models import PresentationIR, GroupElementIR

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}

# Features the engine treats as safe to edit.
SUPPORTED_FEATURES = frozenset({"shape", "text", "image", "group", "table", "theme"})

# Features that are detectable but NOT safe to edit.
DETECT_ONLY_FEATURES = frozenset({"chart", "smartart", "animation", "master_slide"})

# Features that parse/edit losslessly in IR but whose OOXML write-back is lossy.
# Format: feature -> machine-readable degradation reason.
# - table: TableElementIR is currently exported as a Group of styled cell
#   rectangles, permanently dropping native <a:tbl> semantics (row/column
#   editing, merged cells, table styles). Do NOT treat "group with cell text"
#   as table preservation.
LOSSY_WRITEBACK_FEATURES: Dict[str, str] = {
    "table": "flattened_to_group",
}


@dataclass
class FidelityCapability:
    """Per-file OOXML feature presence + engine support matrix.

    Defaults represent the ENGINE's support boundary (what we can safely edit).
    A detected FidelityCapability reflects which features a specific file actually uses.
    """

    shape: bool = True
    text: bool = True
    image: bool = True
    group: bool = True
    table: bool = True
    chart: bool = False
    smartart: bool = False
    animation: bool = False
    master_slide: bool = False
    theme: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return {
            "shape": self.shape,
            "text": self.text,
            "image": self.image,
            "group": self.group,
            "table": self.table,
            "chart": self.chart,
            "smartart": self.smartart,
            "animation": self.animation,
            "master_slide": self.master_slide,
            "theme": self.theme,
        }

    @classmethod
    def engine_supported(cls) -> FidelityCapability:
        """The static engine capability matrix (which features can be edited)."""
        return cls()

    def present_features(self) -> List[str]:
        return [name for name, present in self.to_dict().items() if present]

    def unsupported_present(self) -> List[str]:
        """Features present in the file that the engine cannot safely edit."""
        return [name for name in DETECT_ONLY_FEATURES if getattr(self, name)]

    def unsupported_warnings(self) -> List[str]:
        """Human-readable warnings for unsupported features.

        master_slide is structural (virtually every PPTX contains slide masters), so it is
        excluded from warnings to avoid noise; it remains reported in the capabilities dict.
        """
        warnings = []
        for name in self.unsupported_present():
            if name == "master_slide":
                continue
            warnings.append(
                f"presentation uses {name}, which the Fidelity Engine can detect but not safely edit"
            )
        return warnings

    @classmethod
    def lossy_writeback_features(cls) -> Dict[str, str]:
        """Declarative map of features whose export degrades native OOXML semantics."""
        return dict(LOSSY_WRITEBACK_FEATURES)

    def lossy_warnings(self) -> List[str]:
        """Warnings for features present in this file that will degrade on export."""
        warnings = []
        for name, reason in LOSSY_WRITEBACK_FEATURES.items():
            if getattr(self, name, False):
                warnings.append(
                    f"export of {name} is lossy ({reason}): native OOXML semantics are not preserved"
                )
        return warnings


class CapabilityDetector:
    """Detects OOXML feature presence inside a PPTX package (independent of IR parsing)."""

    @classmethod
    def detect(cls, pptx_source: Union[str, bytes, io.BytesIO]) -> FidelityCapability:
        """Detects which OOXML features the package uses."""
        if isinstance(pptx_source, (str, os.PathLike)):
            with zipfile.ZipFile(pptx_source, "r") as zf:
                return cls.detect_in_open_zip(zf)
        elif isinstance(pptx_source, bytes):
            with zipfile.ZipFile(io.BytesIO(pptx_source), "r") as zf:
                return cls.detect_in_open_zip(zf)
        else:
            return cls.detect_in_open_zip(pptx_source)

    @classmethod
    def detect_in_open_zip(cls, zf: zipfile.ZipFile) -> FidelityCapability:
        """Detects OOXML feature presence from an already-open zip archive."""
        return cls._detect_in_zip(zf)

    @classmethod
    def detect_from_ir(cls, pres: PresentationIR, detected: Optional[FidelityCapability] = None) -> FidelityCapability:
        """Merges element-level presence (shape/text/image/group/table) from parsed IR."""
        cap = detected if detected is not None else FidelityCapability()
        has_shape = False
        has_text = False
        has_image = False
        has_group = False
        has_table = False

        for slide in pres.slides:
            for el in slide.all_elements(recursive=True):
                if isinstance(el, GroupElementIR):
                    has_group = True
                    continue
                if el.type == "shape":
                    has_shape = True
                elif el.type == "text":
                    has_text = True
                elif el.type == "image":
                    has_image = True
                elif el.type == "table":
                    has_table = True

        cap.shape = has_shape or cap.shape
        cap.text = has_text or cap.text
        cap.image = has_image or cap.image
        cap.group = has_group or cap.group
        cap.table = has_table or cap.table
        return cap

    @classmethod
    def check_support(cls, feature: str) -> Dict[str, object]:
        """Returns a structured support verdict for a feature.

        >>> CapabilityDetector.check_support("chart")
        {'supported': False, 'reason': 'unsupported_feature'}
        """
        feature_norm = feature.lower().strip()
        if feature_norm in SUPPORTED_FEATURES:
            return {"supported": True, "reason": ""}
        if feature_norm in DETECT_ONLY_FEATURES:
            return {"supported": False, "reason": "unsupported_feature"}
        return {"supported": False, "reason": "unknown_feature"}

    @classmethod
    def check_writeback(cls, feature: str) -> Dict[str, object]:
        """Returns whether exporting a feature preserves native OOXML semantics.

        >>> CapabilityDetector.check_writeback("table")
        {'lossless': False, 'reason': 'flattened_to_group'}
        """
        feature_norm = feature.lower().strip()
        reason = LOSSY_WRITEBACK_FEATURES.get(feature_norm)
        if reason:
            return {"lossless": False, "reason": reason}
        return {"lossless": True, "reason": ""}

    @classmethod
    def _detect_in_zip(cls, zf: zipfile.ZipFile) -> FidelityCapability:
        namelist = set(zf.namelist())
        cap = FidelityCapability()
        cap.chart = cls._has_chart(namelist)
        cap.smartart = cls._has_smartart(namelist)
        cap.master_slide = cls._has_master(namelist)
        cap.theme = cls._has_theme(namelist)
        has_animation, has_table = cls._scan_slide_xmls(zf, namelist)
        cap.animation = has_animation
        cap.table = has_table or cap.table
        return cap

    @staticmethod
    def _has_chart(namelist: Set[str]) -> bool:
        if any(p.startswith("ppt/charts/") for p in namelist):
            return True
        return any(p.startswith("ppt/embeddings/") and p.endswith(".xlsx") for p in namelist)

    @staticmethod
    def _has_smartart(namelist: Set[str]) -> bool:
        return any(p.startswith("ppt/diagrams/") for p in namelist)

    @staticmethod
    def _has_master(namelist: Set[str]) -> bool:
        return any(p.startswith("ppt/slideMasters/") for p in namelist)

    @staticmethod
    def _has_theme(namelist: Set[str]) -> bool:
        return any(p.startswith("ppt/theme/") and p.endswith(".xml") for p in namelist)

    @classmethod
    def _scan_slide_xmls(cls, zf: zipfile.ZipFile, namelist: Set[str]) -> tuple:
        has_animation = False
        has_table = False
        slide_xmls = sorted(
            p for p in namelist if p.startswith("ppt/slides/slide") and p.endswith(".xml")
        )
        for path in slide_xmls:
            try:
                tree = ET.fromstring(zf.read(path))
            except Exception:
                continue
            if not has_animation and tree.find(".//p:timing", NS) is not None:
                has_animation = True
            if not has_table and tree.find(".//a:tbl", NS) is not None:
                has_table = True
            if has_animation and has_table:
                break
        return has_animation, has_table