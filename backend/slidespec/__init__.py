"""Slide Semantic IR Package (PR9).

Bridges PresentationPlan and Layout Engine:
- VisualIntent: Macro layout intent (Title hero, Pipeline architecture, Benchmark comparison, etc.)
- BlockRole: Micro semantic role (Heading, Subheading, Lead summary, Bullet item, Caption, Badge)
- ContentBlock: Abstract content unit (TextBlock, FigureBlock, TableBlock, BadgeBlock)
- SlideSpec / DeckSpec: Structured semantic intermediate representation
- map_presentation_plan_to_deck_spec: Canonical mapper from PresentationPlan to DeckSpec
"""

from .mapper import map_presentation_plan_to_deck_spec, map_slide_plan_to_slide_spec
from .schema import (
    BadgeBlock,
    BlockRole,
    ContentBlock,
    DeckSpec,
    FigureBlock,
    SlideSpec,
    TableBlock,
    TextBlock,
    VisualIntent,
)

__all__ = [
    "VisualIntent",
    "BlockRole",
    "ContentBlock",
    "TextBlock",
    "FigureBlock",
    "TableBlock",
    "BadgeBlock",
    "SlideSpec",
    "DeckSpec",
    "map_slide_plan_to_slide_spec",
    "map_presentation_plan_to_deck_spec",
]
