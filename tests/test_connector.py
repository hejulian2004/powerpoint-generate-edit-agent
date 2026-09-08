"""Unit tests for connector lines, endpoints, and arrow directions."""

import pytest
from pptx_agent_converter.model.shape import ConnectorElement
from pptx_agent_converter.model.style import Line
from pptx_agent_converter.renderer.shape_renderer import ShapeRenderer
from pptx_agent_converter.extractor.style_parser import StyleParser
from pptx_agent_converter.extractor.shape_parser import ShapeParser
from pptx_agent_converter.extractor.text_parser import TextParser


class TestConnector:
    """Tests ensuring connector endpoints and arrow direction fidelity (no reversal)."""

    def test_left_to_right_connector_arrow(self):
        """A ----> B: start=(1.2, 3.5), end=(5.7, 3.5). Arrow must point right."""
        conn = ConnectorElement(
            start=(1.2, 3.5),
            end=(5.7, 3.5),
            arrow_end="triangle",
            line=Line(color="#223344", width=2.0)
        )
        xml_elem = ShapeRenderer.render_connector(conn, shape_id_num=5)

        sp = StyleParser()
        tp = TextParser(sp)
        parser = ShapeParser(sp, tp)
        restored = parser.parse_connector(xml_elem)

        assert restored.start[0] == pytest.approx(1.2, abs=1e-2)
        assert restored.start[1] == pytest.approx(3.5, abs=1e-2)
        assert restored.end[0] == pytest.approx(5.7, abs=1e-2)
        assert restored.end[1] == pytest.approx(3.5, abs=1e-2)
        assert restored.arrow_end == "triangle"
        assert restored.arrow_start is None

    def test_right_to_left_connector_arrow(self):
        """B <---- A: start=(5.7, 3.5), end=(1.2, 3.5). Arrow must point left."""
        conn = ConnectorElement(
            start=(5.7, 3.5),
            end=(1.2, 3.5),
            arrow_end="triangle",
            line=Line(color="#FF0000", width=1.5)
        )
        xml_elem = ShapeRenderer.render_connector(conn, shape_id_num=6)

        sp = StyleParser()
        tp = TextParser(sp)
        parser = ShapeParser(sp, tp)
        restored = parser.parse_connector(xml_elem)

        # Start and end MUST NOT be flipped or reversed
        assert restored.start[0] == pytest.approx(5.7, abs=1e-2)
        assert restored.start[1] == pytest.approx(3.5, abs=1e-2)
        assert restored.end[0] == pytest.approx(1.2, abs=1e-2)
        assert restored.end[1] == pytest.approx(3.5, abs=1e-2)
        assert restored.arrow_end == "triangle"

    def test_upward_and_downward_connectors(self):
        """Test vertical direction preserving."""
        # Upward: start at bottom (y=4.5), end at top (y=1.0)
        up_conn = ConnectorElement(
            start=(2.0, 4.5),
            end=(2.0, 1.0),
            arrow_end="stealth",
            line=Line(color="#00AA00", width=2.0)
        )
        xml_up = ShapeRenderer.render_connector(up_conn, shape_id_num=7)

        sp = StyleParser()
        tp = TextParser(sp)
        parser = ShapeParser(sp, tp)
        restored_up = parser.parse_connector(xml_up)

        assert restored_up.start[1] == pytest.approx(4.5, abs=1e-2)
        assert restored_up.end[1] == pytest.approx(1.0, abs=1e-2)
        assert restored_up.arrow_end == "stealth"

        # Downward: start at top (y=1.0), end at bottom (y=4.5)
        down_conn = ConnectorElement(
            start=(2.0, 1.0),
            end=(2.0, 4.5),
            arrow_end="oval",
            line=Line(color="#00AA00", width=2.0)
        )
        xml_down = ShapeRenderer.render_connector(down_conn, shape_id_num=8)
        restored_down = parser.parse_connector(xml_down)

        assert restored_down.start[1] == pytest.approx(1.0, abs=1e-2)
        assert restored_down.end[1] == pytest.approx(4.5, abs=1e-2)
        assert restored_down.arrow_end == "oval"

    def test_diagonal_connector(self):
        """Diagonal connector with start=(1.0, 1.0), end=(4.0, 5.0)."""
        diag = ConnectorElement(
            start=(1.0, 1.0),
            end=(4.0, 5.0),
            connector_type="bent",
            arrow_end="triangle",
            line=Line(color="#555555", width=2.5)
        )
        xml_elem = ShapeRenderer.render_connector(diag, shape_id_num=9)

        sp = StyleParser()
        tp = TextParser(sp)
        parser = ShapeParser(sp, tp)
        restored = parser.parse_connector(xml_elem)

        assert restored.start[0] == pytest.approx(1.0, abs=1e-2)
        assert restored.start[1] == pytest.approx(1.0, abs=1e-2)
        assert restored.end[0] == pytest.approx(4.0, abs=1e-2)
        assert restored.end[1] == pytest.approx(5.0, abs=1e-2)
        assert restored.connector_type == "bent"
        assert restored.arrow_end == "triangle"
