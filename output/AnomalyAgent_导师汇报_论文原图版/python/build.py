# -*- coding: utf-8 -*-
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
    pres_width = 13.3333
    pres_height = 7.5
    theme_info = ThemeInfo(
        name="Office Theme",
        color_scheme={'dk1': '#000000', 'lt1': '#FFFFFF', 'dk2': '#44546A', 'lt2': '#E7E6E6', 'accent1': '#4472C4', 'accent2': '#ED7D31', 'accent3': '#A5A5A5', 'accent4': '#FFC000', 'accent5': '#5B9BD5', 'accent6': '#70AD47', 'hlink': '#0563C1', 'folHlink': '#954F72', 'dark1': '#000000', 'light1': '#FFFFFF', 'dark2': '#44546A', 'light2': '#E7E6E6'},
        font_scheme={'major': 'Noto Sans CJK SC', 'major_ea': '', 'minor': 'Noto Sans CJK SC', 'minor_ea': ''}
    )

    # Load media files
    media_files = {}
    if os.path.exists(assets_dir):
        for fname in os.listdir(assets_dir):
            fpath = os.path.join(assets_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, "rb") as mf:
                    media_files[fname] = mf.read()

    slides = []
    slide_files = sorted(glob.glob(os.path.join(current_dir, "slide_*.py")))

    for idx, sfile in enumerate(slide_files, start=1):
        mod_name = f"slide_{idx:02d}"
        spec = importlib.util.spec_from_file_location(mod_name, sfile)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        slide = create_slide(slide_id=idx, width=pres_width, height=pres_height)
        if hasattr(mod, "build"):
            mod.build(slide)
        slides.append(slide)

    pres = Presentation(
        name="AnomalyAgent_导师汇报_论文原图版",
        size=SlideSize(width=pres_width, height=pres_height),
        theme=theme_info,
        slides=slides,
        media_files=media_files
    )

    output_pptx = os.path.join(project_dir, "rebuild.pptx")
    builder = PPTXBuilder()
    builder.build(pres, output_pptx)
    print(f"Successfully generated rebuild.pptx at: {output_pptx}")

if __name__ == "__main__":
    main()
