"""Visual Evaluation and Layout Self-Healing Data Schemas (PR12).

Defines core contracts for:
- Visual issue categorization, severity, and evidence (VisualIssue, VLMEvaluationResponse)
- Layout patch representation and atomic operations (LayoutPatch, PatchResult)
- Screenshot metadata and fidelity categorization (ScreenshotBackendType, ScreenshotFidelity, ScreenshotResult)
- Evaluation loop diagnostics and self-healing telemetry (SelfHealingResult, RepairIterationRecord)
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


class VLMEvaluationResponse(BaseModel):
    """Strict container schema enforcing structured VLM critique response."""

    issues: List[VisualIssue] = Field(default_factory=list, description="Validated visual issues extracted from VLM")
    summary: Optional[str] = Field(None, description="Optional high-level evaluation narrative")


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


class PatchResult(BaseModel):
    """Transactional outcome of applying a patch with geometric constraint verification."""

    success: bool = Field(..., description="Whether patch was accepted and committed")
    patch: LayoutPatch = Field(..., description="The patch attempted")
    before_valid: bool = Field(..., description="Layout validation status prior to patch")
    after_valid: bool = Field(..., description="Layout validation status after candidate patch")
    errors_before: List[str] = Field(default_factory=list, description="Validation errors before patch")
    errors_after: List[str] = Field(default_factory=list, description="Validation errors after candidate patch")
    rejected_reason: Optional[str] = Field(None, description="Explanation if candidate patch was rejected/rolled back")


class VisualEvaluationError(RuntimeError):
    """Raised when visual evaluation fails due to client error, timeout, or malformed response."""
    pass


class EvaluationResult(BaseModel):
    """Container for the outcome of a visual evaluation run."""

    success: bool = Field(True, description="Whether visual evaluation succeeded")
    issues: List[VisualIssue] = Field(default_factory=list, description="List of detected visual issues")
    error: Optional[str] = Field(None, description="Error message if evaluation failed")

    def __iter__(self):
        return iter(self.issues)

    def __len__(self) -> int:
        return len(self.issues)

    def __getitem__(self, index: int) -> VisualIssue:
        return self.issues[index]


class ScreenshotBackendType(str, Enum):
    """Rendering backend used to produce slide screenshots."""

    POWERPOINT = "powerpoint"
    LIBREOFFICE = "libreoffice"
    FALLBACK = "fallback"


class ScreenshotFidelity(str, Enum):
    """Confidence level of rendered screenshot relative to native PowerPoint rasterization."""

    NATIVE = "native"
    COMPATIBLE = "compatible"
    APPROXIMATE = "approximate"
    # Backward compatibility alias
    REAL = "native"


class ScreenshotResult(BaseModel):
    """Structured result of PPTX slide screenshot rendering."""

    image_paths: List[Path] = Field(default_factory=list, description="List of exported PNG paths")
    backend: ScreenshotBackendType = Field(..., description="Backend engine utilized")
    fidelity: ScreenshotFidelity = Field(..., description="Visual fidelity level: real/native vs approximate")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Resolution, execution time, etc.")

    def __iter__(self):
        """Allow unpacking or direct iteration over image paths for backward compatibility."""
        return iter(self.image_paths)

    def __len__(self) -> int:
        return len(self.image_paths)

    def __getitem__(self, index: int) -> Path:
        return self.image_paths[index]


class RepairIterationRecord(BaseModel):
    """Snapshot of a single evaluation-and-repair cycle."""

    iteration: int = Field(..., description="1-based iteration counter")
    issues_detected: List[VisualIssue] = Field(default_factory=list, description="Issues before repair")
    patches_applied: List[LayoutPatch] = Field(default_factory=list, description="Patches generated and applied")
    patch_results: List[PatchResult] = Field(default_factory=list, description="Transactional outcomes of patches")
    screenshot_paths: List[str] = Field(default_factory=list, description="Rendered screenshot image paths")
    screenshot_fidelity: Optional[ScreenshotFidelity] = Field(None, description="Fidelity of screenshots evaluated")
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
    final_screenshot_result: Optional[ScreenshotResult] = Field(None, description="Full screenshot metadata")
    evaluation_failed: bool = Field(False, description="Whether evaluation crashed or failed")
    stop_reason: Optional[str] = Field(None, description="Reason for stopping: converged, worsened, oscillated, evaluation_failed, max_iterations")
    error: Optional[str] = Field(None, description="Detailed error message if evaluation failed")

    def to_json_file(self, path: Union[str, Path]) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out
