"""End-to-end roundtrip test: PPTX -> JSON / Python DSL -> PPTX."""

import os
import shutil
import tempfile
import pytest

from pptx_agent_converter.model.slide import Presentation, Slide, SlideSize, ThemeInfo
from pptx_agent_converter.model.shape import (
    ShapeElement,
    ConnectorElement,
    Position
)
from pptx_agent_converter.model.style import Fill, Line, Shadow
from pptx_agent_converter.model.text import TextBlock
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
from pptx_agent_converter.cli import convert_command, build_command, export_slide_command, build_slide_command


@pytest.fixture
def sample_presentation():
    """Builds a rich multi-slide presentation fixture."""
    # Slide 1: RoundRect shape + Connector
    s1 = Slide(slide_id=1, slide_num=1, size=SlideSize(width=13.333, height=7.5))
    s1.elements.append(
        ShapeElement(
            id="101",
            name="Block A",
            shape_type="roundRect",
            position=Position(x=1.2, y=2.5, width=2.0, height=0.8),
            fill=Fill(type="solid", color="#3366FF", alpha=100.0),
            line=Line(color="#FFFFFF", width=1.5),
            shadow=Shadow(enabled=True, color="#000000", alpha=40.0),
            radius=0.1667,
            text=TextBlock.from_simple_text(
                text="Image Generation",
                font_name="Aptos",
                font_size=18.0,
                font_color="#FFFFFF",
                bold=False,
                align="center",
                vertical="middle"
            )
        )
    )
    s1.elements.append(
        ConnectorElement(
            id="102",
            name="Arrow 1",
            connector_type="straight",
            start=(5.7, 3.5),
            end=(6.2, 3.5),
            arrow_end="triangle",
            line=Line(color="#223344", width=2.0)
        )
    )

    # Slide 2: Title and 2 boxes
    s2 = Slide(slide_id=2, slide_num=2, size=SlideSize(width=13.333, height=7.5))
    s2.elements.append(
        ShapeElement(
            id="201",
            name="Title",
            shape_type="rectangle",
            position=Position(x=1.0, y=1.0, width=8.0, height=1.2),
            fill=Fill(type="solid", color="#EEEEEE"),
            text=TextBlock.from_simple_text(
                text="Architecture Overview",
                font_name="Calibri",
                font_size=28.0,
                font_color="#222222",
                bold=True
            )
        )
    )
    s2.elements.append(
        ShapeElement(
            id="202",
            name="Box 1",
            shape_type="ellipse",
            position=Position(x=2.0, y=3.0, width=2.5, height=2.5),
            fill=Fill(type="solid", color="#00AA88"),
            line=Line(color="#004433", width=2.0),
            text=TextBlock.from_simple_text(
                text="Core Engine",
                font_size=16.0,
                font_color="#FFFFFF",
                align="center"
            )
        )
    )

    theme = ThemeInfo(
        name="Custom Theme",
        color_scheme={"accent1": "#3366FF", "dk1": "#000000", "lt1": "#FFFFFF"},
        font_scheme={"major": "Aptos", "minor": "Calibri"}
    )

    return Presentation(
        name="sample_test",
        size=SlideSize(width=13.333, height=7.5),
        theme=theme,
        slides=[s1, s2]
    )


class TestRoundtrip:
    """Tests the full PPTX -> JSON -> PPTX conversion cycle."""

    def test_full_roundtrip_workflow(self, sample_presentation, tmp_path):
        # 1. Create initial PPTX
        input_pptx = str(tmp_path / "original.pptx")
        builder = PPTXBuilder()
        builder.build(sample_presentation, input_pptx)
        assert os.path.exists(input_pptx)

        # 2. Run CLI convert: PPTX -> JSON + Python DSL
        output_dir = str(tmp_path / "output")
        ret = convert_command(input_pptx, output_base_dir=output_dir)
        assert ret == 0

        project_dir = os.path.join(output_dir, "original")
        assert os.path.exists(os.path.join(project_dir, "presentation.json"))
        assert os.path.exists(os.path.join(project_dir, "slides", "slide_01.json"))
        assert os.path.exists(os.path.join(project_dir, "slides", "slide_02.json"))
        assert os.path.exists(os.path.join(project_dir, "python", "slide_01.py"))
        assert os.path.exists(os.path.join(project_dir, "python", "build.py"))

        # 3. Run CLI build: JSON -> PPTX
        rebuild_pptx = str(tmp_path / "rebuild.pptx")
        ret_build = build_command(project_dir, output_path=rebuild_pptx)
        assert ret_build == 0
        assert os.path.exists(rebuild_pptx)

        # 4. Parse rebuild.pptx and compare
        rebuilt_pres = PPTXParser(rebuild_pptx).parse()

        # Compare slide count
        assert len(rebuilt_pres.slides) == len(sample_presentation.slides)

        # Compare Slide 1
        orig_s1 = sample_presentation.slides[0]
        rebuilt_s1 = rebuilt_pres.slides[0]
        assert len(rebuilt_s1.elements) == len(orig_s1.elements)

        orig_shape = orig_s1.elements[0]
        rebuilt_shape = rebuilt_s1.elements[0]
        assert rebuilt_shape.shape_type == orig_shape.shape_type
        assert rebuilt_shape.position.x == pytest.approx(orig_shape.position.x, abs=1e-2)
        assert rebuilt_shape.position.y == pytest.approx(orig_shape.position.y, abs=1e-2)
        assert rebuilt_shape.fill.color == orig_shape.fill.color
        assert rebuilt_shape.text.content == "Image Generation"
        assert rebuilt_shape.text.primary_font.name == "Aptos"

        # Compare Connector
        orig_conn = orig_s1.elements[1]
        rebuilt_conn = rebuilt_s1.elements[1]
        assert isinstance(rebuilt_conn, ConnectorElement)
        assert rebuilt_conn.start[0] == pytest.approx(orig_conn.start[0], abs=1e-2)
        assert rebuilt_conn.end[0] == pytest.approx(orig_conn.end[0], abs=1e-2)
        assert rebuilt_conn.arrow_end == "triangle"

        # Compare Slide 2
        orig_s2 = sample_presentation.slides[1]
        rebuilt_s2 = rebuilt_pres.slides[1]
        assert len(rebuilt_s2.elements) == len(orig_s2.elements)
        assert rebuilt_s2.elements[0].text.content == "Architecture Overview"
        assert rebuilt_s2.elements[1].shape_type == "ellipse"
        assert rebuilt_s2.elements[1].text.content == "Core Engine"

    def test_export_slide_and_build_slide_cli(self, sample_presentation, tmp_path):
        input_pptx = str(tmp_path / "pres.pptx")
        PPTXBuilder().build(sample_presentation, input_pptx)

        # Export slide 2
        slide_out_dir = str(tmp_path / "single_export")
        ret_exp = export_slide_command(input_pptx, slide_num=2, output_dir=slide_out_dir)
        assert ret_exp == 0

        slide_file = os.path.join(slide_out_dir, "slide_02.json")
        assert os.path.exists(slide_file)

        # Build single slide
        single_pptx = str(tmp_path / "slide_02_built.pptx")
        ret_bld = build_slide_command(slide_file, output_path=single_pptx)
        assert ret_bld == 0
        assert os.path.exists(single_pptx)

        parsed_single = PPTXParser(single_pptx).parse()
        assert len(parsed_single.slides) == 1
        assert len(parsed_single.slides[0].elements) == 2
        assert parsed_single.slides[0].elements[0].text.content == "Architecture Overview"

    def test_python_dsl_script_execution(self, sample_presentation, tmp_path):
        """Tests that the generated python/build.py script executes without errors and builds rebuild.pptx."""
        import subprocess
        import sys

        input_pptx = str(tmp_path / "pres_dsl.pptx")
        PPTXBuilder().build(sample_presentation, input_pptx)

        output_dir = str(tmp_path / "output_dsl")
        ret = convert_command(input_pptx, output_base_dir=output_dir)
        assert ret == 0

        project_dir = os.path.join(output_dir, "pres_dsl")
        python_dir = os.path.join(project_dir, "python")
        build_script = os.path.join(python_dir, "build.py")
        assert os.path.exists(build_script)

        # Set PYTHONPATH so build.py finds pptx_agent_converter
        env = os.environ.copy()
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        env["PYTHONPATH"] = workspace_root

        # Execute build.py via subprocess
        res = subprocess.run(
            [sys.executable, build_script],
            cwd=python_dir,
            env=env,
            capture_output=True,
            text=True
        )
        assert res.returncode == 0, f"build.py failed with error:\n{res.stderr}"

        # Verify rebuild.pptx was created by build.py
        rebuild_pptx = os.path.join(project_dir, "rebuild.pptx")
        assert os.path.exists(rebuild_pptx)
        rebuilt_pres = PPTXParser(rebuild_pptx).parse()
        assert len(rebuilt_pres.slides) == 2

    def test_image_roundtrip(self, tmp_path):
        """Tests image extraction to assets and rebuilding back into PPTX."""
        from pptx_agent_converter.model.shape import ImageElement

        # Minimal valid 1x1 PNG
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00'
            b'\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        slide = Slide(slide_id=1, slide_num=1, size=SlideSize(width=13.333, height=7.5))
        img_elem = ImageElement(
            name="Test Logo",
            position=Position(x=1.0, y=1.0, width=3.0, height=2.0),
            src="assets/test_logo.png",
            original_name="test_logo.png"
        )
        slide.elements.append(img_elem)

        pres = Presentation(
            name="image_test",
            size=SlideSize(width=13.333, height=7.5),
            slides=[slide],
            media_files={"test_logo.png": png_bytes}
        )

        input_pptx = str(tmp_path / "img_input.pptx")
        PPTXBuilder().build(pres, input_pptx)
        assert os.path.exists(input_pptx)

        # Convert
        output_dir = str(tmp_path / "output_img")
        ret = convert_command(input_pptx, output_base_dir=output_dir)
        assert ret == 0

        project_dir = os.path.join(output_dir, "img_input")
        extracted_asset = os.path.join(project_dir, "assets", "test_logo.png")
        assert os.path.exists(extracted_asset)
        with open(extracted_asset, "rb") as f:
            assert f.read() == png_bytes

        # Rebuild
        rebuild_pptx = str(tmp_path / "img_rebuild.pptx")
        ret_bld = build_command(project_dir, output_path=rebuild_pptx)
        assert ret_bld == 0

        # Parse rebuilt PPTX
        parsed = PPTXParser(rebuild_pptx).parse()
        assert len(parsed.slides) == 1
        assert len(parsed.slides[0].elements) == 1
        img_restored = parsed.slides[0].elements[0]
        assert isinstance(img_restored, ImageElement)
        assert img_restored.position.x == pytest.approx(1.0, abs=1e-2)
        assert img_restored.position.width == pytest.approx(3.0, abs=1e-2)
        assert "test_logo.png" in parsed.media_files
        assert parsed.media_files["test_logo.png"] == png_bytes

