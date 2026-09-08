"""Unit tests for shape types, fills, borders, shadows, and radii."""

import pytest
import xml.etree.ElementTree as ET

from pptx_agent_converter.model.shape import Position, ShapeElement
from pptx_agent_converter.model.style import Fill, Line, Shadow, GradientStop
from pptx_agent_converter.model.text import TextBlock
from pptx_agent_converter.renderer.shape_renderer import ShapeRenderer
from pptx_agent_converter.extractor.style_parser import StyleParser
from pptx_agent_converter.extractor.shape_parser import ShapeParser
from pptx_agent_converter.extractor.text_parser import TextParser


class TestShape:
    """Test shape types, fills, lines, and effects."""

    @pytest.mark.parametrize("stype", ["rectangle", "roundRect", "ellipse", "diamond", "arrow", "line"])
    def test_shape_types(self, stype):
        shape = ShapeElement(
            shape_type=stype,
            position=Position(x=1.0, y=2.0, width=3.0, height=1.5),
            fill=Fill(type="solid", color="#123456"),
            line=Line(color="#FFFFFF", width=2.0)
        )
        d = shape.to_dict()
        assert d["shape_type"] == stype
        assert d["position"]["x"] == 1.0
        assert d["position"]["width"] == 3.0

        restored = ShapeElement.from_dict(d)
        assert restored.shape_type == stype
        assert restored.fill.color == "#123456"
        assert restored.line.width == 2.0

    def test_shape_roundrect_radius(self):
        shape = ShapeElement(
            shape_type="roundRect",
            position=Position(x=1.2, y=2.5, width=2.0, height=0.8),
            fill=Fill(type="solid", color="#3366FF", alpha=100.0),
            line=Line(color="#FFFFFF", width=1.5),
            shadow=Shadow(enabled=True, color="#000000", alpha=30.0),
            radius=0.1667,
            text=TextBlock.from_simple_text("Image Generation")
        )
        d = shape.to_dict()
        assert d["shape_type"] == "roundRect"
        assert d["radius"] == 0.1667
        assert d["fill"]["color"] == "#3366FF"
        assert d["shadow"]["enabled"] is True

        # Render to OOXML XML
        sp_xml = ShapeRenderer.render_shape(shape, shape_id_num=2)
        assert sp_xml is not None

        # Parse back
        sp = StyleParser()
        tp = TextParser(sp)
        shp_parser = ShapeParser(sp, tp)
        restored = shp_parser.parse_shape(sp_xml)

        assert restored.shape_type == "roundRect"
        assert restored.fill.color == "#3366FF"
        assert restored.line.color == "#FFFFFF"
        assert restored.line.width == 1.5
        assert restored.shadow.enabled is True
        assert restored.text.content == "Image Generation"
        assert restored.radius == pytest.approx(0.1667, abs=1e-3)

    def test_gradient_fill(self):
        stops = [
            GradientStop(position=0.0, color="#FF0000", alpha=100.0),
            GradientStop(position=1.0, color="#0000FF", alpha=50.0)
        ]
        fill = Fill(type="gradient", angle=45.0, stops=stops)
        shape = ShapeElement(
            shape_type="ellipse",
            position=Position(x=0.5, y=0.5, width=2.0, height=2.0),
            fill=fill
        )
        sp_xml = ShapeRenderer.render_shape(shape, shape_id_num=3)

        sp = StyleParser()
        tp = TextParser(sp)
        shp_parser = ShapeParser(sp, tp)
        restored = shp_parser.parse_shape(sp_xml)

        assert restored.fill.type == "gradient"
        assert restored.fill.angle == 45.0
        assert len(restored.fill.stops) == 2
        assert restored.fill.stops[0].color == "#FF0000"
        assert restored.fill.stops[1].color == "#0000FF"
        assert restored.fill.stops[1].alpha == 50.0

    def test_dashed_border_and_transparency(self):
        line = Line(color="#00AA00", width=3.0, alpha=75.0, style="dash")
        shape = ShapeElement(
            shape_type="rectangle",
            position=Position(x=1.0, y=1.0, width=4.0, height=2.0),
            fill=Fill(type="solid", color="#FFAAAA", alpha=50.0),
            line=line
        )
        sp_xml = ShapeRenderer.render_shape(shape, shape_id_num=4)

        sp = StyleParser()
        tp = TextParser(sp)
        shp_parser = ShapeParser(sp, tp)
        restored = shp_parser.parse_shape(sp_xml)

        assert restored.fill.alpha == 50.0
        assert restored.line.style == "dash"
        assert restored.line.width == 3.0
        assert restored.line.alpha == 75.0
