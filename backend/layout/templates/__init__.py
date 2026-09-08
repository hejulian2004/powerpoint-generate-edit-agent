"""Layout Template Registry and Factory Dispatcher (PR10)."""

from __future__ import annotations

from typing import Dict, Type

from ...slidespec.schema import VisualIntent
from .base import BaseLayoutTemplate
from .comparison import BenchmarkComparisonTemplate
from .pipeline import PipelineArchitectureTemplate
from .result import TakeawayListTemplate
from .title import TitleHeroTemplate
from .two_column import TwoColumnContrastTemplate

TEMPLATE_REGISTRY: Dict[VisualIntent, Type[BaseLayoutTemplate]] = {
    VisualIntent.TITLE_HERO: TitleHeroTemplate,
    VisualIntent.PIPELINE_ARCHITECTURE: PipelineArchitectureTemplate,
    VisualIntent.BENCHMARK_COMPARISON: BenchmarkComparisonTemplate,
    VisualIntent.TWO_COLUMN_CONTRAST: TwoColumnContrastTemplate,
    VisualIntent.METRIC_CARD_GRID: TakeawayListTemplate,
    VisualIntent.KEY_TAKEAWAY_LIST: TakeawayListTemplate,
}


def get_template_for_intent(intent: VisualIntent) -> BaseLayoutTemplate:
    """Retrieve an instantiated template handler for a given VisualIntent."""
    template_cls = TEMPLATE_REGISTRY.get(intent, TakeawayListTemplate)
    return template_cls()


__all__ = [
    "BaseLayoutTemplate",
    "TitleHeroTemplate",
    "PipelineArchitectureTemplate",
    "BenchmarkComparisonTemplate",
    "TwoColumnContrastTemplate",
    "TakeawayListTemplate",
    "TEMPLATE_REGISTRY",
    "get_template_for_intent",
]
