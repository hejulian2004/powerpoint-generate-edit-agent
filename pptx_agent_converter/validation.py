"""PPTX Package Validation Utility for PPT-Agent-Studio.

Validates that a given file is a well-formed OOXML PowerPoint package:
- Valid zip archive structure
- Standard presentation.xml exists and is parseable
- Presentation relationships (presentation.xml.rels) are readable
- Slide definitions and corresponding XML parts exist
"""

from __future__ import annotations
import os
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Union
import xml.etree.ElementTree as ET

NS_PRESENTATION = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"


def validate_pptx(path: Union[str, Path, os.PathLike]) -> Dict[str, Any]:
    """Validate a PPTX file structure and return package health status.

    Checks:
    - File exists and is non-empty
    - Valid ZIP archive
    - Contains ppt/presentation.xml
    - Contains ppt/_rels/presentation.xml.rels or readable relationships
    - Contains valid slides matching declared presentation structure

    Returns:
        {
            "valid": bool,
            "slides": int,
            "errors": List[str]
        }
    """
    path_obj = Path(path)
    errors: List[str] = []
    slide_count = 0

    if not path_obj.exists():
        return {
            "valid": False,
            "slides": 0,
            "errors": [f"File not found: {path_obj}"]
        }

    if path_obj.stat().st_size == 0:
        return {
            "valid": False,
            "slides": 0,
            "errors": [f"File is empty (0 bytes): {path_obj}"]
        }

    if not zipfile.is_zipfile(path_obj):
        return {
            "valid": False,
            "slides": 0,
            "errors": [f"File is not a valid zip archive: {path_obj}"]
        }

    try:
        with zipfile.ZipFile(path_obj, "r") as zf:
            namelist = set(zf.namelist())

            # 1. Check ppt/presentation.xml
            if "ppt/presentation.xml" not in namelist:
                errors.append("Missing required OOXML part: ppt/presentation.xml")
            else:
                try:
                    pres_bytes = zf.read("ppt/presentation.xml")
                    pres_root = ET.fromstring(pres_bytes)
                    # Count slides from sldIdLst
                    sld_id_lst = pres_root.find(f"{{{NS_PRESENTATION}}}sldIdLst")
                    if sld_id_lst is not None:
                        slide_count = len(sld_id_lst.findall(f"{{{NS_PRESENTATION}}}sldId"))
                    else:
                        # Fallback: count slide XML files
                        slide_files = [n for n in namelist if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
                        slide_count = len(slide_files)
                except ET.ParseError as pe:
                    errors.append(f"Corrupt XML in ppt/presentation.xml: {pe}")

            # 2. Check ppt/_rels/presentation.xml.rels
            if "ppt/_rels/presentation.xml.rels" not in namelist:
                # Some presentations store rels in alternate paths, but presentation.xml.rels is standard
                errors.append("Missing relationships part: ppt/_rels/presentation.xml.rels")
            else:
                try:
                    rels_bytes = zf.read("ppt/_rels/presentation.xml.rels")
                    ET.fromstring(rels_bytes)
                except ET.ParseError as pe:
                    errors.append(f"Corrupt XML in ppt/_rels/presentation.xml.rels: {pe}")

            # 3. Check slides directory or parts
            slide_parts = [n for n in namelist if n.startswith("ppt/slides/")]
            if slide_count > 0 and not slide_parts:
                errors.append("Declared slides in presentation.xml but no ppt/slides/ entries found")

            # 4. Check Content_Types
            if "[Content_Types].xml" not in namelist:
                errors.append("Missing standard OOXML package descriptor: [Content_Types].xml")

    except zipfile.BadZipFile as bz:
        errors.append(f"Bad zip file: {bz}")
    except Exception as e:
        errors.append(f"Unexpected validation error: {e}")

    return {
        "valid": len(errors) == 0,
        "slides": slide_count,
        "errors": errors
    }
