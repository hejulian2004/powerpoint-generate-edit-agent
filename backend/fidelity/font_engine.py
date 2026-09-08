"""FontEngine: Cross-platform font discovery, matching, and rasterization cascade.

Eliminates Pillow default bitmap font drift by resolving native TrueType/OpenType
fonts across Windows, Linux, and macOS with style (weight, italic) and fallback cascades.
"""

from __future__ import annotations
import os
import glob
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Fallback cascades for generic font classes
SANS_SERIF_CASCADE = [
    "Segoe UI", "Calibri", "Arial", "Helvetica", "Microsoft YaHei", "PingFang SC", "DejaVu Sans"
]
SERIF_CASCADE = [
    "Times New Roman", "Cambria", "Georgia", "SimSun", "DejaVu Serif"
]
MONO_CASCADE = [
    "Consolas", "Courier New", "Cascadia Code", "DejaVu Sans Mono"
]


class FontEngine:
    """Discovers, indexes, and loads TrueType/OpenType fonts for high-fidelity rendering."""

    _font_index: Optional[Dict[str, Dict[str, str]]] = None  # family_lower -> {variant: path}
    _default_font_path: Optional[str] = None

    @classmethod
    def _scan_system_fonts(cls) -> Dict[str, Dict[str, str]]:
        """Scans standard OS font directories and indexes available font files."""
        index: Dict[str, Dict[str, str]] = {}
        search_dirs: List[str] = []

        # Windows
        win_dir = os.environ.get("WINDIR", "C:\\Windows")
        search_dirs.append(os.path.join(win_dir, "Fonts"))
        user_win_fonts = os.path.expanduser("~\\AppData\\Local\\Microsoft\\Windows\\Fonts")
        if os.path.exists(user_win_fonts):
            search_dirs.append(user_win_fonts)

        # Linux / Unix
        search_dirs.extend([
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
            os.path.expanduser("~/.local/share/fonts")
        ])

        # macOS
        search_dirs.extend([
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts")
        ])

        font_extensions = ("*.ttf", "*.otf", "*.ttc", "*.TTF", "*.OTF", "*.TTC")

        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            for ext in font_extensions:
                for file_path in glob.glob(os.path.join(d, ext)):
                    cls._index_font_file(file_path, index)

        return index

    @classmethod
    def _index_font_file(cls, path: str, index: Dict[str, Dict[str, str]]) -> None:
        """Indexes a font file by normalized base name and style heuristics."""
        fname = os.path.splitext(os.path.basename(path))[0].lower()

        # Extract variant: bold, italic, bold_italic, regular
        is_bold = any(b in fname for b in ["bd", "bold", "b", "heavy", "black"])
        is_italic = any(i in fname for i in ["i", "italic", "oblique", "it"])

        variant = "regular"
        if is_bold and is_italic:
            variant = "bold_italic"
        elif is_bold:
            variant = "bold"
        elif is_italic:
            variant = "italic"

        # Normalize family name candidate
        clean_name = fname
        for token in ["bd", "bold", "italic", "bi", "ib", "regular", "reg", "light", "semilight", "ui"]:
            clean_name = clean_name.replace(token, "")
        clean_name = clean_name.strip("_- ")

        # Common known Windows font file mappings
        explicit_mappings = {
            "arial": "arial",
            "arialbd": ("arial", "bold"),
            "ariali": ("arial", "italic"),
            "arialbi": ("arial", "bold_italic"),
            "calibri": "calibri",
            "calibrib": ("calibri", "bold"),
            "calibrii": ("calibri", "italic"),
            "calibriz": ("calibri", "bold_italic"),
            "segoeui": "segoe ui",
            "segoeuib": ("segoe ui", "bold"),
            "segoeuii": ("segoe ui", "italic"),
            "segoeuiz": ("segoe ui", "bold_italic"),
            "times": "times new roman",
            "timesbd": ("times new roman", "bold"),
            "timesi": ("times new roman", "italic"),
            "timesbi": ("times new roman", "bold_italic"),
            "consola": "consolas",
            "consolab": ("consolas", "bold"),
            "consolai": ("consolas", "italic"),
            "consolaz": ("consolas", "bold_italic"),
            "msyh": "microsoft yahei",
            "msyhbd": ("microsoft yahei", "bold"),
            "simsun": "simsun",
        }

        if fname in explicit_mappings:
            entry = explicit_mappings[fname]
            if isinstance(entry, tuple):
                family, var = entry
            else:
                family, var = entry, "regular"
        else:
            family = clean_name if clean_name else fname
            var = variant

        if family not in index:
            index[family] = {}
        index[family][var] = path

    @classmethod
    def get_index(cls) -> Dict[str, Dict[str, str]]:
        if cls._font_index is None:
            cls._font_index = cls._scan_system_fonts()
        return cls._font_index

    @classmethod
    def resolve_font_path(
        cls,
        family: str,
        bold: bool = False,
        italic: bool = False
    ) -> Optional[str]:
        """Resolves font family and style to an existing TTF/OTF font file path."""
        idx = cls.get_index()

        target_variant = "regular"
        if bold and italic:
            target_variant = "bold_italic"
        elif bold:
            target_variant = "bold"
        elif italic:
            target_variant = "italic"

        # Helper to search index for a given family name
        def _find_in_index(fam_name: str) -> Optional[str]:
            norm = fam_name.lower().strip()
            # 1. Exact match
            if norm in idx:
                variants = idx[norm]
                if target_variant in variants:
                    return variants[target_variant]
                # Fallback within same family
                if "regular" in variants:
                    return variants["regular"]
                for p in variants.values():
                    return p

            # 2. Fuzzy substring match (e.g. "calibri light" -> "calibri")
            for k, variants in idx.items():
                if k in norm or norm in k:
                    if target_variant in variants:
                        return variants[target_variant]
                    if "regular" in variants:
                        return variants["regular"]
                    for p in variants.values():
                        return p
            return None

        # 1. Direct query
        matched_path = _find_in_index(family)
        if matched_path and os.path.exists(matched_path):
            return matched_path

        # 2. Cascade fallback
        cascade = SANS_SERIF_CASCADE
        lower_fam = family.lower()
        if any(s in lower_fam for s in ["times", "serif", "georgia", "cambria"]):
            cascade = SERIF_CASCADE
        elif any(m in lower_fam for m in ["mono", "console", "code", "courier"]):
            cascade = MONO_CASCADE

        for fallback in cascade:
            fallback_path = _find_in_index(fallback)
            if fallback_path and os.path.exists(fallback_path):
                return fallback_path

        # 3. Last resort: any valid indexed font file
        for variants in idx.values():
            for p in variants.values():
                if os.path.exists(p):
                    return p

        return None

    @classmethod
    def get_pil_font(
        cls,
        family: str = "Segoe UI",
        size: float = 18.0,
        bold: bool = False,
        italic: bool = False
    ) -> Any:
        """Loads a PIL TrueType font at requested size, or falls back gracefully."""
        try:
            from PIL import ImageFont
        except ImportError:
            return None

        font_size = max(6, int(round(size)))
        font_path = cls.resolve_font_path(family, bold=bold, italic=italic)

        if font_path:
            try:
                return ImageFont.truetype(font_path, font_size)
            except Exception as e:
                logger.debug(f"Failed to load TrueType font from {font_path}: {e}")

        # Fallback to default
        try:
            return ImageFont.load_default()
        except Exception:
            return None
