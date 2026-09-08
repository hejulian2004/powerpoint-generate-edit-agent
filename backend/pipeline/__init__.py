"""PPT-Agent End-to-End Pipeline Package.

Provides modular abstractions for PPT deck import, visual critique, agent orchestration,
iterative self-healing, OOXML export, and validation.
"""

from .result import PipelineResult
from .importer import PPTImporter
from .evaluator import PipelineEvaluator
from .exporter import PPTExporter
from .runner import PPTEndToEndPipeline, main

__all__ = [
    "PPTEndToEndPipeline",
    "PipelineResult",
    "PPTImporter",
    "PipelineEvaluator",
    "PPTExporter",
    "main",
]
