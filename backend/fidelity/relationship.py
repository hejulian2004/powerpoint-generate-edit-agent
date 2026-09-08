"""Relationship: OOXML relationship graph and package asset tracking.

Manages:
- Package .rels, presentation.xml.rels, slideX.xml.rels
- Target resolution, Type namespaces, and rId allocation
- Asset content deduplication via SHA-256
"""

from __future__ import annotations
import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TYPE_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
REL_TYPE_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
REL_TYPE_SLIDE_LAYOUT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
REL_TYPE_SLIDE_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
REL_TYPE_THEME = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
REL_TYPE_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


@dataclass
class RelationshipEntry:
    id: str
    type: str
    target: str
    target_mode: Optional[str] = None  # E.g. "External" for hyperlinks

    def to_xml_element(self) -> ET.Element:
        attrib = {
            "Id": self.id,
            "Type": self.type,
            "Target": self.target,
        }
        if self.target_mode:
            attrib["TargetMode"] = self.target_mode
        return ET.Element(f"{{{RELS_NS}}}Relationship", attrib)


class RelationshipGraph:
    """Represents a collection of relationships corresponding to an OOXML .rels file."""

    def __init__(self, source_path: str = ""):
        self.source_path = source_path
        self._entries: Dict[str, RelationshipEntry] = {}
        self._next_id: int = 1

    @classmethod
    def from_xml_bytes(cls, xml_bytes: bytes, source_path: str = "") -> RelationshipGraph:
        """Parses an OOXML .rels XML document."""
        graph = cls(source_path=source_path)
        if not xml_bytes:
            return graph

        try:
            tree = ET.fromstring(xml_bytes)
            for elem in tree.findall(f"{{{RELS_NS}}}Relationship"):
                r_id = elem.get("Id", "")
                r_type = elem.get("Type", "")
                r_target = elem.get("Target", "")
                r_mode = elem.get("TargetMode")
                if r_id:
                    graph._entries[r_id] = RelationshipEntry(
                        id=r_id,
                        type=r_type,
                        target=r_target,
                        target_mode=r_mode
                    )
                    # Track numerical IDs
                    if r_id.startswith("rId") and r_id[3:].isdigit():
                        graph._next_id = max(graph._next_id, int(r_id[3:]) + 1)
        except Exception:
            pass

        return graph

    def add_relationship(
        self,
        rel_type: str,
        target: str,
        target_mode: Optional[str] = None,
        custom_id: Optional[str] = None
    ) -> str:
        """Adds a relationship and returns the allocated rId."""
        # Deduplicate identical target & type
        for r_id, entry in self._entries.items():
            if entry.type == rel_type and entry.target == target and entry.target_mode == target_mode:
                return r_id

        alloc_id = custom_id or f"rId{self._next_id}"
        self._next_id += 1
        self._entries[alloc_id] = RelationshipEntry(
            id=alloc_id,
            type=rel_type,
            target=target,
            target_mode=target_mode
        )
        return alloc_id

    def add_image_relationship(self, image_target: str) -> str:
        """Adds an image relationship (e.g. '../media/image1.png')."""
        return self.add_relationship(REL_TYPE_IMAGE, image_target)

    def add_hyperlink(self, url: str) -> str:
        """Adds an external hyperlink relationship."""
        return self.add_relationship(REL_TYPE_HYPERLINK, url, target_mode="External")

    def get_target(self, r_id: str) -> Optional[str]:
        entry = self._entries.get(r_id)
        return entry.target if entry else None

    def get_by_type(self, rel_type: str) -> List[RelationshipEntry]:
        return [e for e in self._entries.values() if e.type == rel_type]

    def to_xml_string(self) -> str:
        """Renders standard OOXML .rels XML."""
        root = ET.Element(f"{{{RELS_NS}}}Relationships")
        for entry in sorted(self._entries.values(), key=lambda e: e.id):
            root.append(entry.to_xml_element())
        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


class AssetManager:
    """Tracks binary presentation assets, deduplicating via SHA-256 hashes."""

    @staticmethod
    def compute_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def deduplicate_assets(
        media_files: Dict[str, bytes]
    ) -> Tuple[Dict[str, bytes], Dict[str, str]]:
        """Deduplicates binary assets by SHA-256 hash.

        Returns:
            (unique_media_files: filename -> bytes, filename_remap: orig_name -> canonical_name)
        """
        hash_to_canonical: Dict[str, str] = {}
        unique_media: Dict[str, bytes] = {}
        remap: Dict[str, str] = {}

        for fname, data in media_files.items():
            h = AssetManager.compute_hash(data)
            if h in hash_to_canonical:
                canonical_name = hash_to_canonical[h]
                remap[fname] = canonical_name
            else:
                hash_to_canonical[h] = fname
                unique_media[fname] = data
                remap[fname] = fname

        return unique_media, remap
