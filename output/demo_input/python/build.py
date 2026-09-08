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
    pres_width = 13.333
    pres_height = 7.5
    theme_info = ThemeInfo(
        name="Office Theme",
        color_scheme={'dk1': '#000000', 'lt1': '#FFFFFF', 'dk2': '#1F497D', 'lt2': '#EEECE1', 'accent1': '#3366FF', 'accent2': '#C0504D', 'accent3': '#9BBB59', 'accent4': '#8064A2', 'accent5': '#4BACC6', 'accent6': '#F79646', 'hlink': '#0000FF', 'folHlink': '#800080', 'dark1': '#000000', 'light1': '#FFFFFF', 'dark2': '#1F497D', 'light2': '#EEECE1'},
        font_scheme={'major': 'Aptos', 'major_ea': 'Aptos', 'minor': 'Calibri', 'minor_ea': 'Calibri'}
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
        name="demo_input",
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
