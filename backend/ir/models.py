"""PPT-IR (Presentation Intermediate Representation) Data Models - v2.

The canonical representation used across Agent reasoning, SVG/HTML rendering,
Web editing, and bi-directional OOXML conversion.
Standard canvas dimensions: 1280 x 720 (16:9 ViewBox).

Features in v2:
- True hierarchical GroupElementIR with recursive children and transform nesting
- TransformIR with flip_h, flip_v, scale_x, scale_y and matrix representation
- Rich ParagraphIR (bullet styles, line spacing, space before/after, indent level)
- Rich RunIR (hyperlink, highlight, theme color reference)
- Shape custom geometry and adjust values
- Connector shape-binding (start_shape_id, end_shape_id)
- Master and theme color slot references
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field as dc_field
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Union, Literal, Generator
from pydantic import BaseModel, Field, model_validator
import uuid


# =====================================================================
# Style & Visual Models
# =====================================================================

class GradientStop(BaseModel):
    position: float = Field(0.0, description="Stop position from 0.0 to 1.0")
    color: str = Field("#3B82F6", description="Hex color '#RRGGBB'")
    alpha: float = Field(1.0, description="Opacity from 0.0 to 1.0")


class GradientFill(BaseModel):
    type: Literal["linear", "radial"] = "linear"
    angle: float = Field(90.0, description="Gradient angle in degrees")
    stops: List[GradientStop] = Field(default_factory=list)


class FillStyle(BaseModel):
    type: Literal["none", "solid", "gradient", "theme"] = "solid"
    color: Optional[str] = Field("#3B82F6", description="Hex color")
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    gradient: Optional[GradientFill] = None
    theme_color: Optional[str] = Field(None, description="OOXML theme token: accent1-6, dk1, lt1, etc.")


class BorderStyle(BaseModel):
    color: Optional[str] = Field("#1E293B", description="Border color")
    width: float = Field(1.0, ge=0.0, description="Border width in px")
    style: Literal["solid", "dashed", "dotted", "none"] = "solid"
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    theme_color: Optional[str] = None


class ShadowStyle(BaseModel):
    enabled: bool = False
    color: str = "#000000"
    blur: float = Field(4.0, ge=0.0)
    angle: float = Field(45.0, description="Shadow angle in degrees")
    distance: float = Field(3.0, ge=0.0)
    alpha: float = Field(0.25, ge=0.0, le=1.0)


class FontIR(BaseModel):
    name: str = "Segoe UI"
    size: float = Field(18.0, ge=6.0, description="Font size in px")
    color: str = "#1E293B"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    highlight: Optional[str] = None
    theme_color: Optional[str] = None


class RunIR(BaseModel):
    text: str = ""
    font: Optional[FontIR] = None
    hyperlink: Optional[str] = None


class ParagraphIR(BaseModel):
    align: Literal["left", "center", "right", "justify"] = "left"
    vertical_align: Literal["top", "middle", "bottom"] = "top"
    line_spacing: float = Field(1.2, description="Line height multiplier")
    space_before: float = 0.0
    space_after: float = 0.0
    bullet: Optional[str] = Field(None, description="Bullet symbol, 'none', 'disc', or numbering")
    indent_level: int = Field(0, ge=0, le=9, description="0-based paragraph nesting level")
    margin_left: float = Field(0.0, description="Left indentation margin in px")
    runs: List[RunIR] = Field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "".join(r.text for r in self.runs)


class TextContentIR(BaseModel):
    paragraphs: List[ParagraphIR] = Field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "\n".join(p.plain_text for p in self.paragraphs)

    @classmethod
    def from_plain_text(
        cls,
        text: str,
        font: Optional[FontIR] = None,
        align: Literal["left", "center", "right", "justify"] = "left"
    ) -> TextContentIR:
        paragraphs = []
        for line in text.split("\n"):
            paragraphs.append(ParagraphIR(align=align, runs=[RunIR(text=line, font=font)]))
        return cls(paragraphs=paragraphs)


class ElementStyleIR(BaseModel):
    fill: Optional[FillStyle] = None
    border: Optional[BorderStyle] = None
    shadow: Optional[ShadowStyle] = None
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    radius: float = Field(0.0, description="Normalized border radius 0.0 - 0.5 or px")
    padding: float = Field(8.0, description="Internal padding in px")


# =====================================================================
# Transform & Geometry Models
# =====================================================================

class TransformIR(BaseModel):
    """Canonical geometric transformation on the 1280x720 canvas."""
    x: float = Field(0.0, description="Left position in px")
    y: float = Field(0.0, description="Top position in px")
    width: float = Field(100.0, ge=0.0, description="Width in px")
    height: float = Field(50.0, ge=0.0, description="Height in px")
    rotation: float = Field(0.0, description="Clockwise rotation in degrees")
    flip_h: bool = Field(False, description="Horizontal flip")
    flip_v: bool = Field(False, description="Vertical flip")
    scale_x: float = Field(1.0, description="Local horizontal scale")
    scale_y: float = Field(1.0, description="Local vertical scale")


# =====================================================================
# Element IR Models
# =====================================================================

class BaseElementIR(BaseModel):
    id: str = Field(default_factory=lambda: f"elem_{uuid.uuid4().hex[:8]}")
    type: str
    name: Optional[str] = None
    x: float = Field(0.0, description="Left position in px (1280x720 canvas)")
    y: float = Field(0.0, description="Top position in px")
    width: float = Field(100.0, ge=0.0, description="Width in px")
    height: float = Field(50.0, ge=0.0, description="Height in px")
    rotation: float = Field(0.0, description="Clockwise rotation in degrees")
    transform: Optional[TransformIR] = None
    z_index: int = Field(0, description="Stacking order")
    locked: bool = False
    style: ElementStyleIR = Field(default_factory=ElementStyleIR)
    children: List[ElementIR] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_transform_and_coords(self) -> BaseElementIR:
        """Keep top-level coordinates and transform object bidirectional."""
        if self.transform is None:
            self.transform = TransformIR(
                x=self.x,
                y=self.y,
                width=self.width,
                height=self.height,
                rotation=self.rotation,
            )
        else:
            # Sync to flat fields for backwards compatibility with PR1 code
            self.x = self.transform.x
            self.y = self.transform.y
            self.width = self.transform.width
            self.height = self.transform.height
            self.rotation = self.transform.rotation
        return self


class ShapeElementIR(BaseElementIR):
    type: Literal["shape"] = "shape"
    shape_type: str = Field("roundRect", description="rectangle, roundRect, ellipse, diamond, triangle, rightArrow, callout, star")
    text_content: Optional[TextContentIR] = None
    flip_h: bool = False
    flip_v: bool = False
    adjust_values: Dict[str, float] = Field(default_factory=dict, description="OOXML shape adjustment values (e.g. corner radius)")
    custom_geometry: Optional[str] = Field(None, description="Optional SVG path data for custom shapes")


class TextElementIR(BaseElementIR):
    type: Literal["text"] = "text"
    text_content: TextContentIR = Field(default_factory=TextContentIR)


class ConnectorElementIR(BaseElementIR):
    type: Literal["connector"] = "connector"
    start_x: float = 0.0
    start_y: float = 0.0
    end_x: float = 100.0
    end_y: float = 100.0
    start_shape_id: Optional[str] = Field(None, description="Bound shape ID at start point")
    end_shape_id: Optional[str] = Field(None, description="Bound shape ID at end point")
    start_site_index: Optional[int] = Field(None, description="Connection site anchor index on start shape")
    end_site_index: Optional[int] = Field(None, description="Connection site anchor index on end shape")
    arrow_start: Literal["none", "triangle", "stealth", "oval"] = "none"
    arrow_end: Literal["none", "triangle", "stealth", "oval"] = "triangle"
    line_type: Literal["straight", "elbow", "curved"] = "straight"


class ImageElementIR(BaseElementIR):
    type: Literal["image"] = "image"
    src: str = Field("", description="Asset URL, relative path or data:image/*;base64")
    asset_id: Optional[str] = None
    alt_text: Optional[str] = None
    crop: Optional[Dict[str, float]] = Field(None, description="Normalized crop margins: {left, top, right, bottom}")


class TableCellIR(BaseModel):
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text_content: TextContentIR = Field(default_factory=TextContentIR)
    style: Optional[ElementStyleIR] = None


class TableElementIR(BaseElementIR):
    type: Literal["table"] = "table"
    rows: int = 2
    cols: int = 2
    cells: List[List[TableCellIR]] = Field(default_factory=list)


class GroupElementIR(BaseElementIR):
    """Hierarchical Group container preserving nested structure and coordinate system."""
    type: Literal["group"] = "group"
    children: List[ElementIR] = Field(default_factory=list)

    def add_child(self, child: ElementIR) -> ElementIR:
        self.children.append(child)
        return child

    def get_child(self, child_id: str) -> Optional[ElementIR]:
        for child in self.children:
            if child.id == child_id:
                return child
            if isinstance(child, GroupElementIR):
                sub = child.get_child(child_id)
                if sub:
                    return sub
        return None

    def all_children(self) -> List[ElementIR]:
        result = []
        for child in self.children:
            result.append(child)
            if isinstance(child, GroupElementIR):
                result.extend(child.all_children())
        return result

    def recompute_bounds(self) -> None:
        """Computes and updates bounding box from children in canvas pixels."""
        if not self.children:
            return
        min_x = min(c.x for c in self.children)
        min_y = min(c.y for c in self.children)
        max_x = max(c.x + c.width for c in self.children)
        max_y = max(c.y + c.height for c in self.children)
        self.x = round(min_x, 2)
        self.y = round(min_y, 2)
        self.width = round(max(max_x - min_x, 1.0), 2)
        self.height = round(max(max_y - min_y, 1.0), 2)

    def translate(self, dx: float, dy: float) -> None:
        """Translates group origin and recursively shifts all children."""
        self.x = round(self.x + dx, 2)
        self.y = round(self.y + dy, 2)
        for child in self.children:
            if isinstance(child, GroupElementIR):
                child.translate(dx, dy)
            else:
                child.x = round(child.x + dx, 2)
                child.y = round(child.y + dy, 2)
                if isinstance(child, ConnectorElementIR):
                    child.start_x = round(child.start_x + dx, 2)
                    child.start_y = round(child.start_y + dy, 2)
                    child.end_x = round(child.end_x + dx, 2)
                    child.end_y = round(child.end_y + dy, 2)

    def scale(self, sx: float, sy: float, origin_x: Optional[float] = None, origin_y: Optional[float] = None) -> None:
        """Scales group and all children relative to origin (default top-left of group)."""
        ox = self.x if origin_x is None else origin_x
        oy = self.y if origin_y is None else origin_y

        self.x = round(ox + (self.x - ox) * sx, 2)
        self.y = round(oy + (self.y - oy) * sy, 2)
        self.width = round(self.width * sx, 2)
        self.height = round(self.height * sy, 2)

        for child in self.children:
            if isinstance(child, GroupElementIR):
                child.scale(sx, sy, origin_x=ox, origin_y=oy)
            else:
                child.x = round(ox + (child.x - ox) * sx, 2)
                child.y = round(oy + (child.y - oy) * sy, 2)
                child.width = round(child.width * sx, 2)
                child.height = round(child.height * sy, 2)
                if isinstance(child, ConnectorElementIR):
                    child.start_x = round(ox + (child.start_x - ox) * sx, 2)
                    child.start_y = round(oy + (child.start_y - oy) * sy, 2)
                    child.end_x = round(ox + (child.end_x - ox) * sx, 2)
                    child.end_y = round(oy + (child.end_y - oy) * sy, 2)

    @property
    def text_content(self) -> Optional[TextContentIR]:
        """Aggregate text content from children if any child has text."""
        child_paras = []
        for c in self.children:
            tc = getattr(c, "text_content", None)
            if tc and tc.paragraphs:
                child_paras.extend(tc.paragraphs)
        if child_paras:
            return TextContentIR(paragraphs=child_paras)
        return None


# Union type for polymorphic elements (including GroupElementIR)
ElementIR = Union[
    ShapeElementIR,
    TextElementIR,
    ConnectorElementIR,
    ImageElementIR,
    TableElementIR,
    GroupElementIR,
]


# =====================================================================
# Slide & Presentation Models
# =====================================================================

class SlideIR(BaseModel):
    id: str = Field(default_factory=lambda: f"slide_{uuid.uuid4().hex[:6]}")
    slide_num: int = 1
    title: Optional[str] = None
    width: int = Field(1280, description="Standard canvas width in px")
    height: int = Field(720, description="Standard canvas height in px")
    background: FillStyle = Field(default_factory=lambda: FillStyle(type="solid", color="#FFFFFF", alpha=1.0))
    elements: List[ElementIR] = Field(default_factory=list)
    notes: str = ""
    master: Optional[Dict[str, Any]] = Field(None, description="Master slide layout metadata")
    theme: Optional[Dict[str, Any]] = Field(None, description="Slide-level theme override")
    theme_ref: Optional[str] = Field(None, description="Reference to presentation theme")
    layout_name: Optional[str] = Field(None, description="OOXML layout name, e.g. Title and Content")

    def get_element(self, element_id: str) -> Optional[ElementIR]:
        """Search element by ID recursively across top-level elements and groups."""
        def _search(items: List[ElementIR]) -> Optional[ElementIR]:
            for el in items:
                if el.id == element_id:
                    return el
                if isinstance(el, GroupElementIR):
                    found = _search(el.children)
                    if found:
                        return found
            return None
        return _search(self.elements)

    def all_elements(self, recursive: bool = True) -> List[ElementIR]:
        """Return all elements. If recursive=True, includes children inside groups."""
        if not recursive:
            return list(self.elements)
        result: List[ElementIR] = []
        for el in self.elements:
            result.append(el)
            if isinstance(el, GroupElementIR):
                result.extend(el.all_children())
        return result

    def leaf_elements(self) -> List[ElementIR]:
        """Return only leaf elements (non-groups) across the entire hierarchy."""
        return [el for el in self.all_elements(recursive=True) if not isinstance(el, GroupElementIR)]

    def add_element(self, element: ElementIR) -> ElementIR:
        self.elements.append(element)
        return element

    def remove_element(self, element_id: str) -> bool:
        """Remove an element by ID, searching top-level elements and inside groups."""
        init_len = len(self.elements)
        self.elements = [el for el in self.elements if el.id != element_id]
        if len(self.elements) < init_len:
            return True

        # Search recursively within groups
        for el in self.elements:
            if isinstance(el, GroupElementIR):
                child_init = len(el.children)
                el.children = [c for c in el.children if c.id != element_id]
                if len(el.children) < child_init:
                    return True
                # Recursive group search
                for child in el.children:
                    if isinstance(child, GroupElementIR):
                        if self._remove_from_group(child, element_id):
                            return True
        return False

    def _remove_from_group(self, group: GroupElementIR, element_id: str) -> bool:
        child_init = len(group.children)
        group.children = [c for c in group.children if c.id != element_id]
        if len(group.children) < child_init:
            return True
        for child in group.children:
            if isinstance(child, GroupElementIR):
                if self._remove_from_group(child, element_id):
                    return True
        return False

    def group_elements(
        self,
        element_ids: List[str],
        group_id: Optional[str] = None,
        group_name: str = "Group"
    ) -> Optional[GroupElementIR]:
        """Groups the specified elements into a new GroupElementIR container."""
        if not element_ids or len(element_ids) < 2:
            return None

        # Find target elements from top-level elements
        target_ids_set = set(element_ids)
        targets = [el for el in self.elements if el.id in target_ids_set]
        if len(targets) < 2:
            return None

        remaining = [el for el in self.elements if el.id not in target_ids_set]

        min_x = min(t.x for t in targets)
        min_y = min(t.y for t in targets)
        max_x = max(t.x + t.width for t in targets)
        max_y = max(t.y + t.height for t in targets)

        gid = group_id or f"grp_{uuid.uuid4().hex[:6]}"
        new_grp = GroupElementIR(
            id=gid,
            name=group_name,
            x=round(min_x, 2),
            y=round(min_y, 2),
            width=round(max(max_x - min_x, 1.0), 2),
            height=round(max(max_y - min_y, 1.0), 2),
            children=targets
        )

        remaining.append(new_grp)
        self.elements = remaining
        return new_grp

    def ungroup_elements(self, group_id: str) -> List[ElementIR]:
        """Dissolves the specified group and restores its children to slide top-level elements."""
        grp_idx = None
        for idx, el in enumerate(self.elements):
            if el.id == group_id and isinstance(el, GroupElementIR):
                grp_idx = idx
                break

        if grp_idx is None:
            return []

        grp = self.elements.pop(grp_idx)
        # Children coordinates are in absolute slide canvas pixels; restore in-place
        for offset, c in enumerate(grp.children):
            self.elements.insert(grp_idx + offset, c)
        return grp.children


@dataclass
class PresentationSnapshot:
    """Complete, isolated state snapshot of PresentationIR and history stack depth."""
    id: str
    title: str
    width: int
    height: int
    theme: Dict[str, Any]
    master: Optional[Dict[str, Any]]
    slides: List[SlideIR]
    active_slide_id: Optional[str]
    version: int
    assets: Dict[str, str]
    asset_metadata: Dict[str, Any]
    metadata: Dict[str, Any]
    undo_stack_depth: Optional[int] = None
    redo_stack_depth: Optional[int] = None
    raw_dump: Optional[Dict[str, Any]] = None


class PresentationTransaction:
    """Represents an atomic transaction session on a PresentationIR with rollback capability."""

    def __init__(
        self,
        presentation: PresentationIR,
        name: str,
        snapshot: Union[PresentationSnapshot, Dict[str, Any]],
        history: Optional[Any] = None
    ):
        self.presentation = presentation
        self.name = name
        self.snapshot = snapshot
        self.history = history
        self.is_aborted: bool = False
        self.is_committed: bool = False
        self.rollback_reason: Optional[str] = None

    def rollback(self, reason: str = ""):
        """Explicitly abort and revert changes to pre-transaction snapshot."""
        self.is_aborted = True
        self.rollback_reason = reason
        self.presentation.restore_snapshot(self.snapshot, history=self.history)

    def commit(self):
        """Mark transaction as committed successfully."""
        self.is_committed = True

    def __enter__(self) -> PresentationTransaction:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback(reason=str(exc_val) if exc_val else "Exception during transaction")
            return False
        if self.is_aborted:
            self.presentation.restore_snapshot(self.snapshot, history=self.history)
        return False


class PresentationIR(BaseModel):
    id: str = Field(default_factory=lambda: f"pres_{uuid.uuid4().hex[:8]}")
    title: str = "PPT-Agent-Studio Presentation"
    width: int = 1280
    height: int = 720
    theme: Dict[str, Any] = Field(default_factory=lambda: {
        "name": "Modern Clean",
        "primary_color": "#2563EB",
        "secondary_color": "#0F172A",
        "background_color": "#FFFFFF",
        "card_background": "#F8FAFC",
        "font_heading": "Segoe UI",
        "font_body": "Segoe UI",
        "color_scheme": {
            "accent1": "#2563EB",
            "accent2": "#0EA5E9",
            "accent3": "#10B981",
            "accent4": "#F59E0B",
            "accent5": "#EF4444",
            "accent6": "#8B5CF6",
            "dk1": "#0F172A",
            "lt1": "#FFFFFF",
            "dk2": "#334155",
            "lt2": "#F8FAFC",
            "hlink": "#2563EB",
            "folHlink": "#7C3AED",
        },
        "font_scheme": {
            "major_font": "Segoe UI",
            "minor_font": "Segoe UI"
        }
    })
    master: Optional[Dict[str, Any]] = Field(None, description="Presentation-level master layout definitions")
    slides: List[SlideIR] = Field(default_factory=list)
    active_slide_id: Optional[str] = None
    version: int = 1
    assets: Dict[str, str] = Field(default_factory=dict, description="asset_id -> base64 or path")
    asset_metadata: Dict[str, Any] = Field(default_factory=dict, description="asset_id -> {mime_type, width, height, hash}")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata e.g. fix iterations, user preferences")

    def create_snapshot(self, history: Optional[Any] = None) -> PresentationSnapshot:
        """Creates a deep isolated snapshot of the entire presentation state and history depth."""
        return PresentationSnapshot(
            id=self.id,
            title=self.title,
            width=self.width,
            height=self.height,
            theme=copy.deepcopy(self.theme),
            master=copy.deepcopy(self.master),
            slides=[copy.deepcopy(s) for s in self.slides],
            active_slide_id=self.active_slide_id,
            version=self.version,
            assets=copy.deepcopy(self.assets),
            asset_metadata=copy.deepcopy(self.asset_metadata),
            metadata=copy.deepcopy(self.metadata),
            undo_stack_depth=len(history.undo_stack) if (history is not None and hasattr(history, "undo_stack")) else None,
            redo_stack_depth=len(history.redo_stack) if (history is not None and hasattr(history, "redo_stack")) else None,
            raw_dump=copy.deepcopy(self.model_dump())
        )

    def restore_snapshot(
        self,
        snapshot: Union[PresentationSnapshot, Dict[str, Any]],
        history: Optional[Any] = None
    ) -> None:
        """Restores presentation state entirely from snapshot, preserving slide references in-place."""
        if isinstance(snapshot, dict):
            rebuilt = PresentationIR.model_validate(snapshot)
            snap_slides = rebuilt.slides
            self.id = rebuilt.id
            self.title = rebuilt.title
            self.width = rebuilt.width
            self.height = rebuilt.height
            self.theme = rebuilt.theme
            self.master = rebuilt.master
            self.active_slide_id = rebuilt.active_slide_id
            self.version = rebuilt.version
            self.assets = rebuilt.assets
            self.asset_metadata = rebuilt.asset_metadata
            self.metadata = rebuilt.metadata
            undo_depth = None
            redo_depth = None
        else:
            snap_slides = snapshot.slides
            self.id = snapshot.id
            self.title = snapshot.title
            self.width = snapshot.width
            self.height = snapshot.height
            self.theme = copy.deepcopy(snapshot.theme)
            self.master = copy.deepcopy(snapshot.master)
            self.active_slide_id = snapshot.active_slide_id
            self.version = snapshot.version
            self.assets = copy.deepcopy(snapshot.assets)
            self.asset_metadata = copy.deepcopy(snapshot.asset_metadata)
            self.metadata = copy.deepcopy(snapshot.metadata)
            undo_depth = snapshot.undo_stack_depth
            redo_depth = snapshot.redo_stack_depth

        # In-place slide state update to keep active references valid
        slide_map = {s.id: s for s in self.slides}
        updated_slides = []
        for new_s in snap_slides:
            if new_s.id in slide_map:
                old_s = slide_map[new_s.id]
                for f_name in SlideIR.model_fields.keys():
                    setattr(old_s, f_name, copy.deepcopy(getattr(new_s, f_name)))
                updated_slides.append(old_s)
            else:
                updated_slides.append(copy.deepcopy(new_s))

        self.slides = updated_slides

        # Rollback history stacks if history manager is provided
        if history is not None and hasattr(history, "undo_stack"):
            if undo_depth is not None and len(history.undo_stack) > undo_depth:
                del history.undo_stack[undo_depth:]
            if redo_depth is not None and len(history.redo_stack) > redo_depth:
                del history.redo_stack[redo_depth:]

    @contextmanager
    def transaction(
        self,
        name: str = "transaction",
        history: Optional[Any] = None
    ) -> Generator[PresentationTransaction, None, None]:
        """Context manager providing atomicity, commit, and rollback capabilities."""
        snapshot = self.create_snapshot(history=history)
        tx = PresentationTransaction(self, name, snapshot, history=history)
        try:
            yield tx
            if tx.is_aborted:
                self.restore_snapshot(snapshot, history=history)
        except Exception:
            self.restore_snapshot(snapshot, history=history)
            raise

    def get_slide(self, slide_id_or_num: Union[str, int]) -> Optional[SlideIR]:
        if isinstance(slide_id_or_num, int):
            for s in self.slides:
                if s.slide_num == slide_id_or_num:
                    return s
            if 0 <= slide_id_or_num < len(self.slides):
                return self.slides[slide_id_or_num]
        else:
            for s in self.slides:
                if s.id == slide_id_or_num:
                    return s
        return None

    def get_active_slide(self) -> Optional[SlideIR]:
        if self.active_slide_id:
            slide = self.get_slide(self.active_slide_id)
            if slide:
                return slide
        return self.slides[0] if self.slides else None


# Rebuild recursive models in Pydantic v2
BaseElementIR.model_rebuild()
GroupElementIR.model_rebuild()
SlideIR.model_rebuild()
PresentationIR.model_rebuild()
