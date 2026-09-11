"""Custom TypeScript generator for the canonical presentation IR contract.

`frontend/src/types/presentation-ir.generated.ts` is the frontend source of
truth for IR types. It is generated from the Pydantic JSON schema
(`backend/ir/schema_export.py`) so the frontend and backend can never drift
silently.

Design notes
------------
* Field sets and field types are derived entirely from the backend schema: a
  new/renamed/type-changed backend field changes the generated output.
* Requiredness is read from each schema model's ``required`` array, which
  ``backend.ir.schema_export`` sources from the curated structural-field
  registry. This generator holds no requiredness list of its own, so the TS
  contract and the JSON schema can never disagree.
* Regenerate with ``python -m backend.ir.ts_export`` and verify with
  ``python -m backend.ir.ts_export --check`` (enforced in CI).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema_export import build_schema

OUTPUT_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "types"
    / "presentation-ir.generated.ts"
)

GENERATED_HEADER = (
    "// AUTO-GENERATED FILE. DO NOT EDIT.\n"
    "// Source of truth: backend/ir/models.py (via backend.ir.ts_export).\n"
    "// Regenerate: python -m backend.ir.ts_export\n"
)

# Deterministic emission order.
MODEL_ORDER = [
    "GradientStop",
    "GradientFill",
    "FillStyle",
    "BorderStyle",
    "ShadowStyle",
    "FontIR",
    "RunIR",
    "ParagraphIR",
    "TextContentIR",
    "ElementStyleIR",
    "TransformIR",
    "ShapeElementIR",
    "TextElementIR",
    "ConnectorElementIR",
    "ImageElementIR",
    "TableCellIR",
    "TableElementIR",
    "GroupElementIR",
    "SlideIR",
    "PresentationIR",
]

# Frontend-only derived fields not present in the wire schema.
FRONTEND_DERIVED_FIELDS: Dict[str, Dict[str, str]] = {
    "TextContentIR": {"plain_text": "string"},
}


def _merged_defs(schema: Dict[str, Any]) -> Dict[str, Any]:
    defs: Dict[str, Any] = {}
    for model in schema["models"].values():
        defs.update(model.get("$defs", {}))
    return defs


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _parenthesize(type_text: str) -> str:
    if " | " in type_text and not type_text.startswith("("):
        return f"({type_text})"
    return type_text


def _render_type(node: Dict[str, Any]) -> str:
    if not node:
        return "any"
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]
    if "const" in node:
        return _literal(node["const"])
    if "enum" in node:
        return " | ".join(_literal(v) for v in node["enum"])

    for key in ("anyOf", "oneOf"):
        if key in node:
            parts = [_render_type(sub) for sub in node[key]]
            # Preserve order while de-duplicating null.
            unique: List[str] = []
            for part in parts:
                if part not in unique:
                    unique.append(part)
            return " | ".join(unique)

    node_type = node.get("type")
    if node_type == "array":
        return f"{_parenthesize(_render_type(node.get('items', {})))}[]"
    if node_type == "object" or "additionalProperties" in node:
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            return f"Record<string, {_render_type(additional)}>"
        return "Record<string, any>"
    if node_type in ("integer", "number"):
        return "number"
    if node_type == "boolean":
        return "boolean"
    if node_type == "string":
        return "string"
    if node_type == "null":
        return "null"
    return "any"


def _render_model(name: str, body: Dict[str, Any]) -> str:
    required = set(body.get("required", []))
    properties = body.get("properties", {})
    derived = FRONTEND_DERIVED_FIELDS.get(name, {})

    lines = [f"export interface {name} {{"]
    for field, spec in properties.items():
        type_text = _render_type(spec)
        optional = field not in required
        marker = "?" if optional else ""
        lines.append(f"  {field}{marker}: {type_text}")
    for field, type_text in derived.items():
        lines.append(f"  {field}?: {type_text}")
    lines.append("}")
    return "\n".join(lines)


def _element_union(defs: Dict[str, Any], schema: Dict[str, Any]) -> str:
    slide = schema["models"].get("SlideIR") or defs.get("SlideIR")
    items = slide["properties"]["elements"]["items"]
    names = [_render_type(sub) for sub in items.get("anyOf", [])]
    unique: List[str] = []
    for n in names:
        if n not in unique:
            unique.append(n)
    return "export type ElementIR = " + " | ".join(unique) + "\n"


def render_typescript() -> str:
    schema = build_schema()
    defs = _merged_defs(schema)

    blocks: List[str] = [GENERATED_HEADER]
    for name in MODEL_ORDER:
        if name == "SlideIR":
            blocks.append(_element_union(defs, schema))
        body = defs.get(name) or schema["models"].get(name)
        if body is None:
            raise KeyError(f"Model {name} missing from exported schema")
        blocks.append(_render_model(name, body))

    return "\n".join(blocks).rstrip("\n") + "\n"


def write_typescript(path: Path = OUTPUT_PATH) -> None:
    path.write_text(render_typescript(), encoding="utf-8")


def check_typescript(path: Path = OUTPUT_PATH) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == render_typescript()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate frontend IR TypeScript types.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the checked-in file is out of date.",
    )
    args = parser.parse_args(argv)

    if args.check:
        if check_typescript():
            print(f"OK: {OUTPUT_PATH} is up to date.")
            return 0
        print(
            f"DRIFT: {OUTPUT_PATH} is stale. Run `python -m backend.ir.ts_export`.",
            file=sys.stderr,
        )
        return 1

    write_typescript()
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
