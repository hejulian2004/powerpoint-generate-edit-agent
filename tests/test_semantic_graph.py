"""Unit tests for PR6.2 Semantic Element Graph and Role Classification."""

import pytest
from backend.semantic import RoleClassifier, SemanticRole, SemanticElementGraph
from backend.agent.action import ActionResolver, AgentAction
from backend.ir.models import (
    SlideIR, ShapeElementIR, TextElementIR, ImageElementIR,
    ConnectorElementIR, TextContentIR, RunIR, ParagraphIR, FontIR, FillStyle
)


def test_role_classifier_and_graph_construction():
    slide = SlideIR(id="slide_dash", slide_num=1)

    # Title: top prominent header
    title_el = TextElementIR(
        id="t1",
        name="Header",
        x=100.0, y=50.0, width=800.0, height=60.0,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(runs=[RunIR(text="Q3 Financial Executive Overview", font=FontIR(size=32.0, bold=True))])
        ])
    )
    # Subtitle: below title
    sub_el = TextElementIR(
        id="sub1",
        name="Subtitle",
        x=100.0, y=120.0, width=600.0, height=40.0,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(runs=[RunIR(text="Revenue growth, operating margin, and unit economics", font=FontIR(size=18.0))])
        ])
    )
    # Card 1 container: enclosing KPI metric and description
    card1 = ShapeElementIR(
        id="c1",
        name="KPI Card Container",
        shape_type="roundRect",
        x=100.0, y=200.0, width=320.0, height=240.0,
        style=dict(fill=FillStyle(type="solid", color="#F8FAFC"))
    )
    # Metric inside card 1
    metric1 = TextElementIR(
        id="m1",
        name="Revenue Stat",
        x=120.0, y=220.0, width=280.0, height=60.0,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(runs=[RunIR(text="$48.5M", font=FontIR(size=36.0, bold=True))])
        ])
    )
    # Body text inside card 1
    body1 = TextElementIR(
        id="b1",
        name="Revenue Desc",
        x=120.0, y=300.0, width=280.0, height=80.0,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(runs=[RunIR(text="+24% YoY expansion across enterprise tier", font=FontIR(size=14.0))])
        ])
    )
    # Footer
    footer1 = TextElementIR(
        id="f1",
        name="Footer Page Number",
        x=100.0, y=660.0, width=200.0, height=30.0,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(runs=[RunIR(text="Confidential - Internal Only | Slide 1", font=FontIR(size=10.0))])
        ])
    )

    slide.add_element(title_el)
    slide.add_element(sub_el)
    slide.add_element(card1)
    slide.add_element(metric1)
    slide.add_element(body1)
    slide.add_element(footer1)

    graph = SemanticElementGraph(slide)

    # 1. Title verification
    title_res = graph.get_title()
    assert title_res is not None
    assert title_res.id == "t1"

    # 2. Roles classification
    assert graph.classifications["t1"].role == SemanticRole.SLIDE_TITLE
    assert graph.classifications["sub1"].role == SemanticRole.SUBTITLE
    assert graph.classifications["c1"].role == SemanticRole.CARD
    assert graph.classifications["m1"].role == SemanticRole.METRIC
    assert graph.classifications["b1"].role == SemanticRole.BODY
    assert graph.classifications["f1"].role == SemanticRole.FOOTER

    # 3. Containment query
    contained = graph.get_contained_elements("c1")
    contained_ids = [el.id for el in contained]
    assert "m1" in contained_ids
    assert "b1" in contained_ids

    # 4. Relations output format
    summary_m1 = graph.get_node_summary("m1")
    assert summary_m1 is not None
    assert summary_m1["role"] == "metric"
    assert any("inside:c1" in r for r in summary_m1["relations"])

    # 5. Graph serialization
    graph_dict = graph.to_dict()
    assert graph_dict["title_id"] == "t1"
    assert len(graph_dict["nodes"]) == 6


def test_action_resolver_semantic_targeting():
    slide = SlideIR(id="s1", slide_num=1)
    title_el = TextElementIR(
        id="elem_hdr",
        x=100.0, y=50.0, width=700.0, height=60.0,
        text_content=TextContentIR.from_plain_text("Annual Performance Review")
    )
    metric_el = TextElementIR(
        id="elem_kpi",
        x=100.0, y=200.0, width=200.0, height=80.0,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(runs=[RunIR(text="99.9%", font=FontIR(size=40.0, bold=True))])
        ])
    )
    card_el = ShapeElementIR(
        id="elem_bg_card",
        x=80.0, y=180.0, width=300.0, height=200.0,
        style=dict(fill=FillStyle(type="solid", color="#FFFFFF"))
    )

    slide.add_element(title_el)
    slide.add_element(card_el)
    slide.add_element(metric_el)

    # Resolve target "title" -> finds title_el
    res_title = ActionResolver.resolve_target_element("title", slide)
    assert res_title is not None
    assert res_title.id == "elem_hdr"

    # Resolve target "metric" -> finds metric_el
    res_metric = ActionResolver.resolve_target_element("metric", slide)
    assert res_metric is not None
    assert res_metric.id == "elem_kpi"

    # Resolve target "card" -> finds card_el
    res_card = ActionResolver.resolve_target_element("card", slide)
    assert res_card is not None
    assert res_card.id == "elem_bg_card"
