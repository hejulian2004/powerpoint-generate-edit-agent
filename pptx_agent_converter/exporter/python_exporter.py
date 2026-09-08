"""Python DSL exporter for slides and build runner."""

from __future__ import annotations
import os
from typing import Optional, List, Dict, Any

from ..model.slide import Presentation, Slide
from ..model.shape import (
    ShapeElement,
    ConnectorElement,
    ImageElement,
    GroupElement
)


class PythonDSLExporter:
    """Exports Slide and Presentation objects as executable Python DSL files."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def export_presentation(self, pres: Presentation) -> str:
        """
        Exports python DSL files to:
        - python/slide_01.py
        - python/slide_02.py
        - python/build.py
        """
        python_dir = os.path.join(self.output_dir, pres.name, "python")
        os.makedirs(python_dir, exist_ok=True)

        for slide in pres.slides:
            fname = f"slide_{slide.slide_id:02d}.py"
            code = self.generate_slide_code(slide)
            with open(os.path.join(python_dir, fname), "w", encoding="utf-8") as f:
                f.write(code)

        # Generate build.py
        build_code = self.generate_build_runner_code(pres)
        with open(os.path.join(python_dir, "build.py"), "w", encoding="utf-8") as f:
            f.write(build_code)

        return python_dir

    def generate_slide_code(self, slide: Slide) -> str:
        """Generates Python DSL code for a single slide."""
        lines = [
            "# -*- coding: utf-8 -*-",
            f"# Slide {slide.slide_id:02d} Definition DSL",
            "from pptx_agent_converter.dsl import (",
            "    Shape,",
            "    Connector,",
            "    TextBox,",
            "    Image,",
            "    add_shape,",
            "    add_connector,",
            "    add_textbox,",
            "    add_image",
            ")\n",
            "def build(slide):",
        ]

        if not slide.elements:
            lines.append("    pass  # Empty slide")
            return "\n".join(lines) + "\n"

        for elem in slide.elements:
            if isinstance(elem, ShapeElement):
                lines.extend(self._format_shape(elem))
            elif isinstance(elem, ConnectorElement):
                lines.extend(self._format_connector(elem))
            elif isinstance(elem, ImageElement):
                lines.extend(self._format_image(elem))

        return "\n".join(lines) + "\n"

    def _format_shape(self, shape: ShapeElement) -> List[str]:
        lines = [
            "    add_shape(",
            "        slide,",
            "        Shape(",
            f"            type={shape.shape_type!r},",
            f"            x={round(shape.position.x, 3)},",
            f"            y={round(shape.position.y, 3)},",
            f"            width={round(shape.position.width, 3)},",
            f"            height={round(shape.position.height, 3)},",
        ]
        if shape.rotation:
            lines.append(f"            rotation={round(shape.rotation, 2)},")
        if shape.radius is not None:
            lines.append(f"            radius={round(shape.radius, 4)},")

        style_dict: Dict[str, Any] = {}
        if shape.fill and shape.fill.type != "none":
            style_dict["fill"] = shape.fill.color or "#FFFFFF"
        if shape.line and shape.line.color:
            style_dict["border"] = shape.line.color
            if shape.line.width != 1.0:
                style_dict["border_width"] = round(shape.line.width, 2)
        if shape.shadow and shape.shadow.enabled:
            style_dict["shadow"] = True

        if style_dict:
            lines.append(f"            style={repr(style_dict)},")

        if shape.text and shape.text.content:
            lines.append(f"            text={shape.text.content!r},")
            font_info = shape.text.primary_font.to_dict()
            para_info = shape.text.primary_paragraph_style.to_dict()
            lines.append(f"            font={repr(font_info)},")
            lines.append(f"            paragraph={repr(para_info)},")

        lines.append("        )")
        lines.append("    )\n")
        return lines

    def _format_connector(self, conn: ConnectorElement) -> List[str]:
        lines = [
            "    add_connector(",
            "        slide,",
            f"        start=({round(conn.start[0], 3)}, {round(conn.start[1], 3)}),",
            f"        end=({round(conn.end[0], 3)}, {round(conn.end[1], 3)}),",
        ]
        if conn.arrow_end and conn.arrow_end != "none":
            lines.append(f"        arrow={conn.arrow_end!r},")
        if conn.arrow_start and conn.arrow_start != "none":
            lines.append(f"        arrow_start={conn.arrow_start!r},")
        if conn.connector_type != "straight":
            lines.append(f"        type={conn.connector_type!r},")
        if conn.line.color != "#333333" or conn.line.width != 1.5:
            lines.append(f"        line={repr(conn.line.to_dict())},")

        lines.append("    )\n")
        return lines

    def _format_image(self, img: ImageElement) -> List[str]:
        lines = [
            "    add_image(",
            "        slide,",
            f"        src={img.src!r},",
            f"        x={round(img.position.x, 3)},",
            f"        y={round(img.position.y, 3)},",
            f"        width={round(img.position.width, 3)},",
            f"        height={round(img.position.height, 3)},",
        ]
        if img.rotation:
            lines.append(f"        rotation={round(img.rotation, 2)},")
        lines.append("    )\n")
        return lines

    def generate_build_runner_code(self, pres: Presentation) -> str:
        """Generates build.py script that compiles all slide_XX.py into rebuild.pptx."""
        slide_count = len(pres.slides)
        code = f'''# -*- coding: utf-8 -*-
"""Build runner to compile Python DSL slide definitions into rebuild.pptx."""

import os
import sys
import glob
import importlib.util

# Ensure workspace root and current package are in sys.path
_current = os.path.dirname(os.path.abspath(__file__))
_proj = os.path.dirname(_current)
_workspace = os.path.dirname(os.path.dirname(_proj))
for _p in [_workspace, _proj, _current]:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from pptx_agent_converter.model import Presentation, SlideSize, ThemeInfo
from pptx_agent_converter.dsl import create_slide
from pptx_agent_converter.renderer import PPTXBuilder

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(current_dir)
    assets_dir = os.path.join(project_dir, "assets")

    # Presentation Metadata
    pres_width = {pres.size.width}
    pres_height = {pres.size.height}
    theme_info = ThemeInfo(
        name="{pres.theme.name}",
        color_scheme={repr(pres.theme.color_scheme)},
        font_scheme={repr(pres.theme.font_scheme)}
    )

    # Load media files
    media_files = {{}}
    if os.path.exists(assets_dir):
        for fname in os.listdir(assets_dir):
            fpath = os.path.join(assets_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, "rb") as mf:
                    media_files[fname] = mf.read()

    slides = []
    slide_files = sorted(glob.glob(os.path.join(current_dir, "slide_*.py")))

    for idx, sfile in enumerate(slide_files, start=1):
        mod_name = f"slide_{{idx:02d}}"
        spec = importlib.util.spec_from_file_location(mod_name, sfile)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        slide = create_slide(slide_id=idx, width=pres_width, height=pres_height)
        if hasattr(mod, "build"):
            mod.build(slide)
        slides.append(slide)

    pres = Presentation(
        name="{pres.name}",
        size=SlideSize(width=pres_width, height=pres_height),
        theme=theme_info,
        slides=slides,
        media_files=media_files
    )

    output_pptx = os.path.join(project_dir, "rebuild.pptx")
    builder = PPTXBuilder()
    builder.build(pres, output_pptx)
    print(f"Successfully generated rebuild.pptx at: {{output_pptx}}")

if __name__ == "__main__":
    main()
'''
        return code
