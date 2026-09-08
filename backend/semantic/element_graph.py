"""SemanticElementGraph: Spatial, topological, and role relationship graph for slides.

Provides:
- Role-aware querying (e.g. find_by_role("slide_title"))
- Spatial relationships (above, below, left_of, right_of, aligned:center, aligned:left)
- Hierarchical containment (inside, contains)
- Clean JSON serializable element representations for LLM prompt context
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any, Union
from .role_classifier import RoleClassifier, SemanticRole, ElementClassification
from ..ir.models import SlideIR, ElementIR, ConnectorElementIR
from ..eval.layout_diff import BoundingBox


class SemanticElementGraph:
    """Graph structure connecting slide elements by semantic role and spatial relations."""

    def __init__(self, slide: SlideIR):
        self.slide = slide
        self.elements_by_id: Dict[str, ElementIR] = {el.id: el for el in slide.elements}
        self.boxes: Dict[str, BoundingBox] = {el.id: BoundingBox.from_element(el) for el in slide.elements}
        self.classifications: Dict[str, ElementClassification] = RoleClassifier.classify_slide(slide)
        self.relationships: Dict[str, List[str]] = self._build_relationships()

    def _build_relationships(self) -> Dict[str, List[str]]:
        rels: Dict[str, List[str]] = {eid: [] for eid in self.elements_by_id}

        element_ids = list(self.elements_by_id.keys())
        for i in range(len(element_ids)):
            id_a = element_ids[i]
            box_a = self.boxes[id_a]
            role_a = self.classifications[id_a].role.value

            for j in range(len(element_ids)):
                if i == j:
                    continue
                id_b = element_ids[j]
                box_b = self.boxes[id_b]
                role_b = self.classifications[id_b].role.value

                # 1. Containment (inside / contains)
                if box_a.contains(box_b, tolerance=4.0):
                    rels[id_a].append(f"contains:{id_b}")
                    rels[id_b].append(f"inside:{id_a}")

                # 2. Vertical adjacency (above / below)
                if box_a.bottom <= box_b.top + 10.0 and abs(box_a.center_x - box_b.center_x) < max(box_a.width, box_b.width):
                    rels[id_a].append(f"above:{role_b}")

                # 3. Horizontal adjacency (left_of / right_of)
                if box_a.right <= box_b.left + 10.0 and abs(box_a.center_y - box_b.center_y) < max(box_a.height, box_b.height):
                    rels[id_a].append(f"left_of:{role_b}")

                # 4. Alignment
                if abs(box_a.center_x - box_b.center_x) < 4.0:
                    rels[id_a].append(f"aligned:center")
                elif abs(box_a.left - box_b.left) < 4.0:
                    rels[id_a].append(f"aligned:left")
                elif abs(box_a.top - box_b.top) < 4.0:
                    rels[id_a].append(f"aligned:top")

            # Connector target binding
            el_a = self.elements_by_id[id_a]
            if isinstance(el_a, ConnectorElementIR):
                if el_a.start_shape_id:
                    rels[id_a].append(f"connects_from:{el_a.start_shape_id}")
                if el_a.end_shape_id:
                    rels[id_a].append(f"connects_to:{el_a.end_shape_id}")

            # Deduplicate relation list
            rels[id_a] = list(dict.fromkeys(rels[id_a]))

        return rels

    def get_title(self) -> Optional[ElementIR]:
        """Returns the element classified as slide_title, or highest-ranked title candidate."""
        for eid, cl in self.classifications.items():
            if cl.role == SemanticRole.SLIDE_TITLE:
                return self.elements_by_id.get(eid)
        return None

    def get_title_with_confidence(self) -> Optional[tuple]:
        """Returns (element, confidence) for the classified slide title, or None."""
        for eid, cl in self.classifications.items():
            if cl.role == SemanticRole.SLIDE_TITLE:
                return (self.elements_by_id.get(eid), cl.confidence)
        return None

    def get_element_confidence(self, element_id: str) -> Optional[float]:
        """Returns the semantic classification confidence for an element, or None."""
        cl = self.classifications.get(element_id)
        return cl.confidence if cl else None

    def find_by_role(self, role: Union[str, SemanticRole]) -> List[ElementIR]:
        """Finds all elements matching a semantic role (e.g. 'card', 'body', 'metric')."""
        target_role = role.value if isinstance(role, SemanticRole) else role.lower()
        res: List[ElementIR] = []
        for eid, cl in self.classifications.items():
            if cl.role.value == target_role or target_role in cl.tags:
                el = self.elements_by_id.get(eid)
                if el:
                    res.append(el)
        return res

    def get_containers(self) -> List[ElementIR]:
        """Finds all container / card elements enclosing other elements."""
        return self.find_by_role(SemanticRole.CARD)

    def get_contained_elements(self, container_id: str) -> List[ElementIR]:
        """Finds all elements positioned inside the specified container element."""
        c_box = self.boxes.get(container_id)
        if not c_box:
            return []
        res: List[ElementIR] = []
        for eid, box in self.boxes.items():
            if eid != container_id and c_box.contains(box, tolerance=4.0):
                el = self.elements_by_id.get(eid)
                if el:
                    res.append(el)
        return res

    def get_relations(self, element_id: str) -> List[str]:
        """Returns list of spatial & semantic relationships for an element."""
        return self.relationships.get(element_id, [])

    def get_node_summary(self, element_id: str) -> Optional[Dict[str, Any]]:
        """Returns the structured node summary as requested by PR6.2."""
        cl = self.classifications.get(element_id)
        if not cl:
            return None
        return {
            "id": element_id,
            "role": cl.role.value,
            "importance": cl.importance,
            "confidence": cl.confidence,
            "relations": self.get_relations(element_id)
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the complete semantic graph for agent prompt embedding."""
        nodes = []
        for eid in self.elements_by_id:
            s = self.get_node_summary(eid)
            if s:
                nodes.append(s)
        return {
            "slide_id": self.slide.id,
            "title_id": self.get_title().id if self.get_title() else None,
            "nodes": nodes
        }
