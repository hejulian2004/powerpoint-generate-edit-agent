"""Visual Evaluation and Layout Self-Healing System (PR12).

Public API exports:
- VisualIssue, IssueType, IssueSeverity
- LayoutPatch, PatchOperation, SelfHealingResult, RepairIterationRecord
- ScreenshotRenderer, ScreenshotBackend, PowerPointBackend, LibreOfficeBackend, FallbackScreenshotBackend, render_screenshots
- VisualEvaluator, RuleBasedEvaluator, OpenAICompatibleVisionEvaluator
- apply_patch, apply_patches, apply_deck_patches
- generate_patches_for_issues, evaluate_and_repair
- group_issues_by_slide, filter_issues_by_severity, deduplicate_issues, serialize_issues_json, deserialize_issues_json
"""

from .evaluator import (
    OpenAICompatibleVisionEvaluator,
    RuleBasedEvaluator,
    VisualEvaluator,
)
from .issues import (
    deduplicate_issues,
    deserialize_issues_json,
    filter_issues_by_severity,
    group_issues_by_slide,
    has_blocking_errors,
    serialize_issues_json,
)
from .patch import (
    apply_deck_patches,
    apply_patch,
    apply_patches,
)
from .repair import (
    evaluate_and_repair,
    generate_patches_for_issues,
)
from .schema import (
    IssueSeverity,
    IssueType,
    LayoutPatch,
    PatchOperation,
    RepairIterationRecord,
    SelfHealingResult,
    VisualIssue,
)
from .screenshot import (
    FallbackScreenshotBackend,
    LibreOfficeBackend,
    PowerPointBackend,
    ScreenshotBackend,
    ScreenshotRenderer,
    render_screenshots,
)

__all__ = [
    # Schemas
    "VisualIssue",
    "IssueType",
    "IssueSeverity",
    "LayoutPatch",
    "PatchOperation",
    "RepairIterationRecord",
    "SelfHealingResult",
    # Screenshots
    "ScreenshotRenderer",
    "ScreenshotBackend",
    "PowerPointBackend",
    "LibreOfficeBackend",
    "FallbackScreenshotBackend",
    "render_screenshots",
    # Evaluators
    "VisualEvaluator",
    "RuleBasedEvaluator",
    "OpenAICompatibleVisionEvaluator",
    # Patching & Repair
    "apply_patch",
    "apply_patches",
    "apply_deck_patches",
    "generate_patches_for_issues",
    "evaluate_and_repair",
    # Issue helpers
    "group_issues_by_slide",
    "filter_issues_by_severity",
    "has_blocking_errors",
    "deduplicate_issues",
    "serialize_issues_json",
    "deserialize_issues_json",
]
