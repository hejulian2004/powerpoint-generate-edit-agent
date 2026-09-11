"""Phase 7: backend/frontend IR contract cannot drift silently.

`frontend/src/types/ppt.ts` mirrors the Pydantic IR models. The generated
`frontend/src/types/ir.schema.json` pins the backend contract; this test fails
when a model changed without regenerating the schema.
"""

from backend.ir import schema_export
from backend.ir.models import PresentationIR, SlideIR


def test_checked_in_ir_schema_exists():
    assert schema_export.SCHEMA_PATH.exists(), (
        "missing frontend/src/types/ir.schema.json — "
        "run `python -m backend.ir.schema_export`."
    )


def test_checked_in_ir_schema_matches_models():
    assert schema_export.check_schema(), (
        "IR schema drifted from backend models. Run "
        "`python -m backend.ir.schema_export` and commit the updated "
        "frontend/src/types/ir.schema.json."
    )


def _without_required(body: dict) -> dict:
    body = {k: v for k, v in body.items() if k != "required"}
    if "$defs" in body:
        body["$defs"] = {
            name: _without_required(def_body)
            for name, def_body in body["$defs"].items()
        }
    return body


def test_exported_schema_covers_core_models():
    schema = schema_export.build_schema()
    # `build_schema` injects the curated structural `required` arrays on top of
    # Pydantic's output, so compare everything else.
    assert _without_required(schema["models"]["PresentationIR"]) == _without_required(
        PresentationIR.model_json_schema()
    )
    assert _without_required(schema["models"]["SlideIR"]) == _without_required(
        SlideIR.model_json_schema()
    )
    # Element models are reachable via refs so the whole IR graph is frozen.
    defs = schema["models"]["PresentationIR"].get("$defs", {})
    assert "SlideIR" in defs
    assert any(name.endswith("ElementIR") for name in defs)


def test_schema_carries_curated_structural_required_fields():
    schema = schema_export.build_schema()
    defs = schema["models"]["PresentationIR"].get("$defs", {})
    assert defs["FontIR"]["required"] == ["color", "name", "size"]
    assert "id" in schema["models"]["SlideIR"]["required"]
    assert "slides" in schema["models"]["PresentationIR"]["required"]


def test_schema_export_rejects_required_field_missing_from_model():
    # Fails closed: a required entry that no longer exists on the model raises
    # rather than silently emitting a bogus TS field.
    import pytest

    from backend.ir import schema_export

    original = schema_export.REQUIRED_FIELDS["FontIR"]
    schema_export.REQUIRED_FIELDS["FontIR"] = {"this_field_does_not_exist"}
    try:
        with pytest.raises(KeyError, match="FontIR"):
            schema_export.build_schema()
    finally:
        schema_export.REQUIRED_FIELDS["FontIR"] = original
