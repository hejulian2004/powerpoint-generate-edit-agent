"""Determinism & Reproducibility Tests for Layout Engine (PR10)."""

import hashlib

from backend.layout import generate_layout
from backend.presentation.schema import SlideType
from backend.slidespec.schema import (
    FigureBlock,
    SlideSpec,
    TextBlock,
    VisualIntent,
)


def test_layout_generation_100_runs_determinism():
    slide = SlideSpec(
        index=5,
        slide_type=SlideType.METHOD_DETAIL,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        title="Attention Routing and Geometry Synthesizer",
        subtitle="Detailed specification of the constraint solver",
        blocks=[
            TextBlock(content="Step 1: Parse AST and extract bound attributes"),
            TextBlock(content="Step 2: Solve 2D spatial collision inequalities"),
            TextBlock(content="Step 3: Render verified primitives to LayoutSpec"),
            FigureBlock(
                source_figure_id="figure2",
                caption="Detailed internal state transitions",
                xref_label="Fig. 2",
            ),
        ],
    )

    hashes = set()
    first_json = None

    for _ in range(100):
        layout = generate_layout(slide, validate=True, strict=True)
        # Exclude metadata timestamps if any, but our model is strictly deterministic
        data_json = layout.model_dump_json()
        if first_json is None:
            first_json = data_json

        h = hashlib.sha256(data_json.encode("utf-8")).hexdigest()
        hashes.add(h)

    assert len(hashes) == 1, "Layout generation produced non-deterministic outputs across 100 runs"
