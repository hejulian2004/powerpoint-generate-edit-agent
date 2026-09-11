"""Exports JSON Schemas for the canonical IR contract.

The frontend `src/types/ppt.ts` mirrors these Pydantic models by hand. To stop
the two from drifting silently, the generated schema is checked in and verified
by `tests/test_ir_schema_drift.py` (run as part of the backend suite). When a
model changes, regenerate with:

    python -m backend.ir.schema_export

and commit the updated `frontend/src/types/ir.schema.json` together with the
model change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .models import PresentationIR, SlideIR

SCHEMA_VERSION = 1

# Top-level wire models. Nested models appear under `$defs` via JSON Schema refs.
EXPORTED_MODELS = {
    "PresentationIR": PresentationIR,
    "SlideIR": SlideIR,
}

ELEMENT_BASE = {"id", "type", "x", "y", "width", "height", "rotation", "z_index", "style"}

# Structural fields that every caller must supply even though Pydantic assigns
# them a default. This is the SINGLE source of requiredness: it is injected into
# the exported schema as each model's `required` array, and the TypeScript
# generator reads `required` from the schema instead of keeping its own copy.
REQUIRED_FIELDS: Dict[str, set] = {
    "GradientStop": {"position", "color", "alpha"},
    "GradientFill": {"type", "angle", "stops"},
    "FillStyle": {"type", "alpha"},
    "BorderStyle": {"width", "style", "alpha"},
    "ShadowStyle": {"enabled", "color", "blur", "angle", "distance", "alpha"},
    "FontIR": {"name", "size", "color"},
    "RunIR": {"text"},
    "ParagraphIR": {"align", "line_spacing", "runs"},
    "TextContentIR": {"paragraphs"},
    "ElementStyleIR": {"opacity", "radius", "padding"},
    "TransformIR": {"x", "y", "width", "height", "rotation"},
    "ShapeElementIR": set(ELEMENT_BASE) | {"shape_type"},
    "TextElementIR": set(ELEMENT_BASE) | {"text_content"},
    "ConnectorElementIR": set(ELEMENT_BASE)
    | {"start_x", "start_y", "end_x", "end_y", "arrow_start", "arrow_end", "line_type"},
    "ImageElementIR": set(ELEMENT_BASE) | {"src"},
    "TableCellIR": {"row", "col", "text_content"},
    "TableElementIR": set(ELEMENT_BASE) | {"rows", "cols", "cells"},
    "GroupElementIR": set(ELEMENT_BASE) | {"children"},
    "SlideIR": {"id", "slide_num", "width", "height", "background", "elements"},
    "PresentationIR": {"id", "title", "width", "height", "theme", "slides", "version", "assets"},
}

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "ir.schema.json"
)


def _inject_required(name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Augments a model schema with the curated structural `required` list.

    Fails closed when the registry references a field the schema does not
    declare, so a renamed/removed model field cannot silently drift.
    """
    required = REQUIRED_FIELDS.get(name)
    if required is None:
        return body
    properties = body.get("properties", {})
    unknown = sorted(f for f in required if f not in properties)
    if unknown:
        raise KeyError(f"{name}.required references unknown fields: {unknown}")
    augmented = dict(body)
    augmented["required"] = sorted(required)
    return augmented


def build_schema() -> Dict[str, Any]:
    """Build the deterministic schema document for the exported IR models."""
    models: Dict[str, Any] = {}
    for name, model in EXPORTED_MODELS.items():
        body = model.model_json_schema()
        # Nested models live in `$defs`; annotate each with its required set.
        defs = body.get("$defs")
        if defs:
            body = {**body, "$defs": {
                def_name: _inject_required(def_name, def_body)
                for def_name, def_body in defs.items()
            }}
        models[name] = _inject_required(name, body)
    return {
        "generated_by": "backend/ir/schema_export.py",
        "schema_version": SCHEMA_VERSION,
        "models": models,
    }


def render_schema() -> str:
    """Stable serialization so the drift check is byte-for-byte reproducible."""
    return json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_schema(path: Path = SCHEMA_PATH) -> None:
    path.write_text(render_schema(), encoding="utf-8")


def check_schema(path: Path = SCHEMA_PATH) -> bool:
    """True when the checked-in schema matches the current models."""
    return path.exists() and path.read_text(encoding="utf-8") == render_schema()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export the canonical IR JSON schema.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the checked-in schema is out of date.",
    )
    args = parser.parse_args()

    if args.check:
        if check_schema():
            print(f"IR schema up to date: {SCHEMA_PATH}")
        else:
            raise SystemExit(
                "IR schema is out of date. Run `python -m backend.ir.schema_export`."
            )
    else:
        write_schema()
        print(f"Wrote IR schema: {SCHEMA_PATH}")
