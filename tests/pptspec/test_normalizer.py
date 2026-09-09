"""Unit tests for Normalizer Pipeline (PR13 Step 2)."""

import pytest
from backend.pptspec.normalizer import (
    normalize_dict_to_canonical_spec,
    compute_spec_summary,
    normalize_presentation_input,
)


def test_source_policy_safe_overrides():
    """Verify that even if user JSON attempts to allow invented numbers, normalizer forces safe defaults."""
    malicious_dict = {
        "presentation": {"title": "Test Title"},
        "source_policy": {
            "allow_invented_numbers": True,
            "allow_synthetic_figures": True,
            "allow_external_knowledge": True,
        },
        "slides": [{"title": "Intro"}],
    }

    warnings = []
    spec = normalize_dict_to_canonical_spec(malicious_dict, warnings)
    assert spec.source_policy.allow_invented_numbers is False
    assert spec.source_policy.allow_synthetic_figures is False
    assert spec.source_policy.allow_external_knowledge is False


@pytest.mark.anyio
async def test_incomplete_table_demotion():
    """Verify that missing table rows or row length mismatches demote to placeholder without failing normalization."""
    raw = """
    We present Table 3: Summary of Baseline Latencies.
    Details on page 7.
    """

    res = await normalize_presentation_input(raw, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert res.summary["table_placeholders"] == 1
    assert res.summary["complete_tables"] == 0

    # Ensure no dummy rows are generated
    tbl_ev = [ev for ev in res.spec.evidence if ev.kind == "table"][0]
    assert tbl_ev.complete_table is False
    assert len(tbl_ev.rows) == 0


@pytest.mark.anyio
async def test_compute_spec_summary():
    raw_json = """{
        "raw_text": "Claim 1. Claim 2. Acc achieves 90%. Fig 1 is on page 2. Table data: A, B.",
        "presentation": {"title": "Summary Test"},
        "evidence": [
            {"id": "c1", "kind": "claim", "content": "Claim 1"},
            {"id": "c2", "kind": "claim", "content": "Claim 2"},
            {"id": "m1", "kind": "metric", "name": "Acc", "value": "90%"},
            {"id": "f1", "kind": "figure_reference", "label": "Fig 1", "source_page": 2},
            {"id": "t1", "kind": "table", "columns": ["A", "B"], "rows": [["1", "2"]]},
            {"id": "t2", "kind": "table", "columns": ["A", "B"], "rows": [["1"]]}
        ],
        "slides": [
            {"id": "s1", "title": "S1", "evidence_refs": ["c1", "m1"]},
            {"id": "s2", "title": "S2", "evidence_refs": ["f1", "t1", "t2"]}
        ]
    }"""
    res = await normalize_presentation_input(raw_json, strict_truthfulness=True)
    assert res.valid is True
    summary = res.summary
    assert summary["slides"] == 2
    assert summary["claims"] == 2
    assert summary["metrics"] == 1
    assert summary["figures"] == 1
    assert summary["complete_tables"] == 1
    assert summary["table_placeholders"] == 1
