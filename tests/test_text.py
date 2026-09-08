"""Unit tests for text parsing, font, and paragraph formatting."""

import pytest
import xml.etree.ElementTree as ET

from pptx_agent_converter.model.style import Font, ParagraphStyle
from pptx_agent_converter.model.text import Run, Paragraph, TextBlock
from pptx_agent_converter.renderer.style_renderer import StyleRenderer
from pptx_agent_converter.extractor.style_parser import StyleParser
from pptx_agent_converter.extractor.text_parser import TextParser
from pptx_agent_converter.extractor.constants import NS


class TestText:
    """Test font properties, paragraph styles, and text blocks."""

    def test_font_model_to_dict_and_from_dict(self):
        font = Font(
            name="Aptos",
            size=18.0,
            bold=True,
            italic=False,
            color="#3366FF",
            alpha=80.0
        )
        d = font.to_dict()
        assert d["name"] == "Aptos"
        assert d["size"] == 18.0
        assert d["bold"] is True
        assert d["italic"] is False
        assert d["color"] == "#3366FF"
        assert d["alpha"] == 80.0

        restored = Font.from_dict(d)
        assert restored.name == "Aptos"
        assert restored.size == 18.0
        assert restored.bold is True
        assert restored.color == "#3366FF"
        assert restored.alpha == 80.0

    def test_text_block_simple_content(self):
        tb = TextBlock.from_simple_text(
            text="Image Generation",
            font_name="Aptos",
            font_size=18.0,
            font_color="#FFFFFF",
            bold=False,
            italic=False,
            align="center",
            vertical="middle"
        )
        assert tb.content == "Image Generation"
        assert tb.primary_font.name == "Aptos"
        assert tb.primary_font.size == 18.0
        assert tb.primary_font.color == "#FFFFFF"
        assert tb.primary_paragraph_style.align == "center"
        assert tb.primary_paragraph_style.vertical == "middle"

        d = tb.to_dict()
        assert d["content"] == "Image Generation"
        assert d["font"]["name"] == "Aptos"
        assert d["font"]["color"] == "#FFFFFF"
        assert d["paragraph"]["align"] == "center"

    def test_multi_paragraph_and_runs(self):
        p1 = Paragraph(
            runs=[
                Run("Hello ", Font(name="Arial", size=20.0, bold=True, color="#112233")),
                Run("World", Font(name="Arial", size=20.0, bold=False, color="#445566"))
            ],
            style=ParagraphStyle(align="left")
        )
        p2 = Paragraph(
            runs=[Run("Second line", Font(name="Calibri", size=14.0, italic=True))],
            style=ParagraphStyle(align="right")
        )
        tb = TextBlock(paragraphs=[p1, p2], vertical_align="top")

        assert tb.content == "Hello World\nSecond line"
        d = tb.to_dict()
        assert "paragraphs" in d
        assert len(d["paragraphs"]) == 2
        assert len(d["paragraphs"][0]["runs"]) == 2

        restored = TextBlock.from_dict(d)
        assert restored.content == "Hello World\nSecond line"
        assert len(restored.paragraphs) == 2
        assert restored.paragraphs[0].runs[0].text == "Hello "
        assert restored.paragraphs[0].runs[0].font.bold is True
        assert restored.paragraphs[1].runs[0].font.italic is True

    def test_ooxml_tx_body_roundtrip(self):
        tb = TextBlock.from_simple_text(
            text="Deep Learning",
            font_name="Calibri",
            font_size=24.0,
            font_color="#FF5500",
            bold=True,
            align="center",
            vertical="middle"
        )
        # Render to XML
        xml_node = StyleRenderer.build_tx_body(tb)
        assert xml_node is not None

        # Parse back
        sp = StyleParser()
        tp = TextParser(sp)
        restored_tb = tp.parse_tx_body(xml_node)

        assert restored_tb is not None
        assert restored_tb.content == "Deep Learning"
        assert restored_tb.primary_font.bold is True
        assert restored_tb.primary_font.size == 24.0
        assert restored_tb.primary_font.color == "#FF5500"
        assert restored_tb.primary_paragraph_style.align == "center"
        assert restored_tb.primary_paragraph_style.vertical == "middle"
