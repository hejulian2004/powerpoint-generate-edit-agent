"""JSON exporter for presentation, slides, and media assets."""

from __future__ import annotations
import os
import json
from typing import Optional, Dict, Any

from ..model.slide import Presentation, Slide


class JSONExporter:
    """Exports Presentation and Slide models into JSON files and asset directories."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def export_presentation(self, pres: Presentation) -> str:
        """
        Exports the entire presentation to:
        - presentation.json
        - slides/slide_XX.json
        - assets/imageX.ext
        Returns the directory path where project was exported.
        """
        proj_dir = os.path.join(self.output_dir, pres.name)
        slides_dir = os.path.join(proj_dir, "slides")
        assets_dir = os.path.join(proj_dir, "assets")

        os.makedirs(slides_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)

        # 1. Export assets (media files)
        for fname, data in pres.media_files.items():
            if not fname:
                continue
            asset_path = os.path.join(assets_dir, fname)
            os.makedirs(os.path.dirname(os.path.abspath(asset_path)), exist_ok=True)
            with open(asset_path, "wb") as f:
                f.write(data)

        # 1.5 Export template theme if available
        if pres.theme_raw_bytes:
            template_dir = os.path.join(proj_dir, "template")
            os.makedirs(template_dir, exist_ok=True)
            with open(os.path.join(template_dir, "theme1.xml"), "wb") as f:
                f.write(pres.theme_raw_bytes)

        # 2. Export individual slides
        for slide in pres.slides:
            self.export_slide(slide, slides_dir)

        # 3. Export presentation.json
        pres_json_path = os.path.join(proj_dir, "presentation.json")
        with open(pres_json_path, "w", encoding="utf-8") as f:
            json.dump(pres.to_dict(), f, indent=4, ensure_ascii=False)

        return proj_dir

    def export_slide(self, slide: Slide, target_dir: str) -> str:
        """Exports a single slide to slide_XX.json in target_dir."""
        os.makedirs(target_dir, exist_ok=True)
        fname = f"slide_{slide.slide_id:02d}.json"
        slide_path = os.path.join(target_dir, fname)
        with open(slide_path, "w", encoding="utf-8") as f:
            json.dump(slide.to_dict(), f, indent=4, ensure_ascii=False)
        return slide_path
