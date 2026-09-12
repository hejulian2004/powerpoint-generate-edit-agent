"""LLM-native presentation design schemas.

The LLM owns visual design. These models capture its decisions; deterministic code
only validates them. There is deliberately NO layout/theme enum here: colors and
composition are produced by the model, not chosen from a catalog.

- ``ColorDirection`` / ``DeckArtDirection``: deck-level design language.
- ``SemanticColorBinding``: stable semantic -> color mapping within a deck.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def _clean_color(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in ("none", "transparent"):
        return text.lower()
    return text


class SemanticColorBinding(BaseModel):
    """A stable semantic color: the same key must not drift within a deck."""

    semantic_key: str = Field(..., description="e.g. 'ours', 'baseline', 'anomaly', 'normal'")
    color: str = Field(..., description="Hex color or theme reference")
    rationale: str = Field("", description="Why this color carries this meaning")

    @field_validator("color")
    @classmethod
    def _validate_color(cls, value: str) -> str:
        cleaned = _clean_color(value)
        if not cleaned:
            raise ValueError("color must be a non-empty color value")
        return cleaned


class ColorDirection(BaseModel):
    """Deck color strategy produced by the model (no preset palette enum)."""

    background_strategy: str = Field("", description="How backgrounds are used")
    surface_strategy: str = Field("", description="How cards/surfaces are used")

    primary_text: str = Field(..., description="Primary text color")
    secondary_text: str = Field(..., description="Secondary text color")

    primary_accent: str = Field(..., description="Primary accent color")
    secondary_accent: Optional[str] = Field(None, description="Optional secondary accent")

    semantic_positive: Optional[str] = Field(None, description="Positive semantic color")
    semantic_negative: Optional[str] = Field(None, description="Negative semantic color")
    semantic_warning: Optional[str] = Field(None, description="Warning semantic color")

    rationale: str = Field("", description="Color rationale")
    bindings: List[SemanticColorBinding] = Field(
        default_factory=list, description="Stable semantic -> color bindings"
    )

    @field_validator(
        "primary_text",
        "secondary_text",
        "primary_accent",
        "secondary_accent",
        "semantic_positive",
        "semantic_negative",
        "semantic_warning",
    )
    @classmethod
    def _normalize_colors(cls, value: Optional[str]) -> Optional[str]:
        return _clean_color(value)


class DeckArtDirection(BaseModel):
    """Deck-level design language. Values are free-form model decisions."""

    design_concept: str = Field("", description="Concept statement for the deck")
    visual_language: str = Field("", description="Overall visual language")
    typography_strategy: str = Field("", description="Typography strategy and hierarchy")
    color_direction: ColorDirection = Field(..., description="Deck color direction")
    spacing_strategy: str = Field("", description="Whitespace / spacing strategy")
    figure_strategy: str = Field("", description="How paper figures are used")
    table_strategy: str = Field("", description="How paper tables are used")
    chart_strategy: str = Field("", description="How charts/plots are used")
    decoration_strategy: str = Field("", description="Decorative element strategy")
    consistency_rules: List[str] = Field(
        default_factory=list, description="Rules the whole deck must follow"
    )
    layout_source: str = Field("llm", description="'llm' (primary) or 'fallback_template'")

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "DeckArtDirection":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "SemanticColorBinding",
    "ColorDirection",
    "DeckArtDirection",
]
