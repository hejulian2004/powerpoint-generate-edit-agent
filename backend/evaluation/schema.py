"""Visual Evaluation and Layout Self-Healing Data Schemas (PR12).

Defines core contracts for:
- Visual issue categorization, severity, and evidence (VisualIssue)
- Layout patch representation and atomic operations (LayoutPatch)
- Evaluation loop diagnostics and self-healing telemetry (SelfHealingResult)
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class IssueType(str, Enum):
    """Categorized visual defect identified during slide evaluation."""

    OVERFLOW = "OVERFLOW"
    TEXT_OVERFLOW = "TEXT_OVERFLOW"
    OVERLAP = "OVERLAP"
    TOO_SMALL = "TOO_SMALL"
    LOW_CONTRAST = "LOW_CONTRAST"
    BAD_ALIGNMENT = "BAD_ALIGNMENT"
    EXCESSIVE_EMPTY_SPACE = "EXCESSIVE_EMPTY_SPACE"
    UNDER_UTILIZED_SPACE = "UNDER_UTILIZED_SPACE"
    WRONG_SCALE = "WRONG_SCALE"
    TEXT_DENSITY_HIGH = "TEXT_DENSITY_HIGH"


class IssueSeverity(str, Enum):
    """Urgency level of a visual issue."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class VisualIssue(BaseModel):
    """Structured report of a visual or geometric problem on a slide."""

    model_config = ConfigDict(populate_by_name=True)

    slide_id: str = Field(..., alias="slide", description="ID of the slide where the defect occurs")
    issue_type: IssueType = Field(..., alias="issue", description="Standard defect type classification")
    severity: IssueSeverity = Field(default=IssueSeverity.WARNING, description="Impact severity of the issue")
    element_id: Optional[str] = Field(None, alias="element", description="Target element ID if localized")
    description: str = Field(..., description="Human-readable explanation of the defect")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic data (bboxes, char count, etc.)")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to standard JSON-compatible dict preserving aliases."""
        return self.model_dump(by_alias=True, mode="json")

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(by_alias=True, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualIssue":
        """Deserialize from dictionary."""
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "VisualIssue":
        """Deserialize from JSON string."""
        return cls.model_validate_json(json_str)


class PatchOperation(str, Enum):
    """Atomic geometric or stylistic transformation applied to a LayoutSpec element."""

    MOVE = "MOVE"
    RESIZE = "RESIZE"
    CHANGE_FONT_SIZE = "CHANGE_FONT_SIZE"
    CHANGE_PADDING = "CHANGE_PADDING"
    CLAMP_TO_CANVAS = "CLAMP_TO_CANVAS"
    SET_COORDINATES = "SET_COORDINATES"


class LayoutPatch(BaseModel):
    """Deterministic modification instruction targeting a slide element in LayoutSpec."""

    model_config = ConfigDict(populate_by_name=True)

    slide_id: str = Field(..., description="Slide ID where modification applies")
    target_element: str = Field(..., alias="element_id", description="Element ID to patch")
    operation: PatchOperation = Field(..., description="Operation category to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Transformation parameters")
    description: Optional[str] = Field(None, description="Diagnostic reasoning for the patch")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, indent: Optional[int] = None) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LayoutPatch":
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "LayoutPatch":
        return cls.model_validate_json(json_str)


class RepairIterationRecord(BaseModel):
    """Snapshot of a single evaluation-and-repair cycle."""

    iteration: int = Field(..., description="1-based iteration counter")
    issues_detected: List[VisualIssue] = Field(default_factory=list, description="Issues before repair")
    patches_applied: List[LayoutPatch] = Field(default_factory=list, description="Patches generated and applied")
    screenshot_paths: List[str] = Field(default_factory=list, description="Rendered screenshot image paths")
    error_count: int = Field(0, description="Count of ERROR and CRITICAL severity issues")
    warning_count: int = Field(0, description="Count of WARNING severity issues")


class SelfHealingResult(BaseModel):
    """Overall outcome of the visual self-healing loop."""

    converged: bool = Field(..., description="Whether all critical visual issues were resolved")
    iterations_run: int = Field(..., description="Total evaluation cycles executed")
    final_issues: List[VisualIssue] = Field(default_factory=list, description="Remaining unresolved issues")
    history: List[RepairIterationRecord] = Field(default_factory=list, description="Per-iteration audit log")
    final_pptx_path: Optional[str] = Field(None, description="Path to the final exported PPTX file")
    final_screenshot_paths: List[str] = Field(default_factory=list, description="Paths to final slide screenshots")

    def to_json_file(self, path: Union[str, Path]) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out
