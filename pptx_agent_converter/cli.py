"""Command-line interface for pptx_agent_converter."""

from __future__ import annotations
import os
import sys
import argparse
from typing import Optional

from .extractor.pptx_parser import PPTXParser
from .exporter.json_exporter import JSONExporter
from .exporter.python_exporter import PythonDSLExporter
from .renderer.pptx_builder import PPTXBuilder


def convert_command(pptx_path: str, output_base_dir: str = "output") -> int:
    """Converts a PPTX into structured JSON, assets, and Python DSL."""
    if not os.path.exists(pptx_path):
        print(f"Error: PPTX file not found: {pptx_path}", file=sys.stderr)
        return 1

    print(f"[*] Parsing OOXML structure from: {pptx_path}...")
    parser = PPTXParser(pptx_path)
    presentation = parser.parse()
    print(f"[+] Successfully parsed presentation '{presentation.name}' with {len(presentation.slides)} slides.")

    # JSON export
    print(f"[*] Exporting JSON models and assets to {output_base_dir}/{presentation.name}...")
    json_exporter = JSONExporter(output_base_dir)
    proj_dir = json_exporter.export_presentation(presentation)

    # Python DSL export
    print(f"[*] Generating Python DSL files in {proj_dir}/python...")
    python_exporter = PythonDSLExporter(output_base_dir)
    python_exporter.export_presentation(presentation)

    print(f"[+] Conversion complete! Project created at:\n    {os.path.abspath(proj_dir)}")
    print(f"    - Presentation metadata: {proj_dir}/presentation.json")
    print(f"    - Slides: {proj_dir}/slides/ (count: {len(presentation.slides)})")
    print(f"    - Assets: {proj_dir}/assets/ (count: {len(presentation.media_files)})")
    print(f"    - Python DSL: {proj_dir}/python/")
    return 0


def build_command(project_dir: str, output_path: Optional[str] = None) -> int:
    """Rebuilds a PPTX file from a converted project directory."""
    if not os.path.exists(project_dir):
        print(f"Error: Project directory not found: {project_dir}", file=sys.stderr)
        return 1

    print(f"[*] Reconstructing PPTX from project: {project_dir}...")
    try:
        out_file = PPTXBuilder.build_from_project(project_dir, output_path)
        print(f"[+] Presentation successfully built:\n    {os.path.abspath(out_file)}")
        return 0
    except Exception as e:
        print(f"Error rebuilding presentation: {e}", file=sys.stderr)
        return 1


def export_slide_command(pptx_path: str, slide_num: int, output_dir: Optional[str] = None) -> int:
    """Exports a single slide from a PPTX to JSON."""
    if not os.path.exists(pptx_path):
        print(f"Error: PPTX file not found: {pptx_path}", file=sys.stderr)
        return 1

    print(f"[*] Parsing slide {slide_num} from: {pptx_path}...")
    parser = PPTXParser(pptx_path)
    presentation = parser.parse()

    target_slide = None
    for s in presentation.slides:
        if s.slide_id == slide_num or s.slide_num == slide_num:
            target_slide = s
            break

    if target_slide is None:
        print(f"Error: Slide number {slide_num} not found (total slides: {len(presentation.slides)})", file=sys.stderr)
        return 1

    if not output_dir:
        output_dir = "."

    json_exporter = JSONExporter(output_dir)
    slide_file = json_exporter.export_slide(target_slide, output_dir)
    print(f"[+] Slide {slide_num} exported to:\n    {os.path.abspath(slide_file)}")
    return 0


def build_slide_command(
    slide_json_path: str,
    output_path: Optional[str] = None,
    assets_dir: Optional[str] = None
) -> int:
    """Rebuilds a 1-slide PPTX from a single slide JSON file."""
    if not os.path.exists(slide_json_path):
        print(f"Error: Slide JSON not found: {slide_json_path}", file=sys.stderr)
        return 1

    print(f"[*] Rebuilding single slide PPTX from: {slide_json_path}...")
    try:
        out_file = PPTXBuilder.build_single_slide(slide_json_path, output_path, assets_dir)
        print(f"[+] Slide presentation successfully built:\n    {os.path.abspath(out_file)}")
        return 0
    except Exception as e:
        print(f"Error rebuilding slide: {e}", file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pptx_agent_converter",
        description="PPTX OOXML Engineering Parser & Rebuilder for PPT Agents"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. convert
    conv_parser = subparsers.add_parser("convert", help="Convert PPTX to JSON and Python DSL")
    conv_parser.add_argument("pptx", help="Path to input .pptx file")
    conv_parser.add_argument("--output", "-o", default="output", help="Base output directory (default: output)")

    # 2. build
    build_parser = subparsers.add_parser("build", help="Rebuild PPTX from converted project folder")
    build_parser.add_argument("project_dir", help="Path to project directory (e.g. output/presentation_name)")
    build_parser.add_argument("--output", "-o", help="Target output PPTX file path")

    # 3. export-slide
    export_slide_parser = subparsers.add_parser("export-slide", help="Export a single slide from PPTX to JSON")
    export_slide_parser.add_argument("pptx", help="Path to input .pptx file")
    export_slide_parser.add_argument("--slide", "-s", type=int, required=True, help="Slide number (1-based)")
    export_slide_parser.add_argument("--output", "-o", help="Output directory for exported slide JSON")

    # 4. build-slide
    build_slide_parser = subparsers.add_parser("build-slide", help="Rebuild single slide PPTX from slide JSON")
    build_slide_parser.add_argument("slide_json", help="Path to slide_XX.json file")
    build_slide_parser.add_argument("--output", "-o", help="Target output PPTX file path")
    build_slide_parser.add_argument("--assets", "-a", help="Path to assets folder containing images")

    args = parser.parse_args(argv)

    if args.command == "convert":
        return convert_command(args.pptx, args.output)
    elif args.command == "build":
        return build_command(args.project_dir, args.output)
    elif args.command == "export-slide":
        return export_slide_command(args.pptx, args.slide, args.output)
    elif args.command == "build-slide":
        return build_slide_command(args.slide_json, args.output, args.assets)

    return 0


if __name__ == "__main__":
    sys.exit(main())
