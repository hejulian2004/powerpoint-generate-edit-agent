"""Flexible Format Parser for External AI Outputs (PR13 Step 2).

Supports:
- JSON (strict)
- JSON_FENCE (markdown ```json ... ```)
- JSON_LIKE (JSON embedded in conversational natural language)
- MARKDOWN (headers ## Slide / ###, bullet points, markdown tables)
- PLAIN_TEXT (e.g. '第1页：研究背景', 'Slide 1: ...')
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class InputFormat(str, Enum):
    JSON = "json"
    JSON_FENCE = "json_fence"
    JSON_LIKE = "json_like"
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"


def detect_format(raw_text: str) -> InputFormat:
    """Detect format of external AI presentation input."""
    text = raw_text.strip()
    if not text:
        return InputFormat.PLAIN_TEXT

    # 1. Pure JSON
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        try:
            json.loads(text)
            return InputFormat.JSON
        except Exception:
            pass

    # 2. JSON Fence
    if "```json" in text or (text.startswith("```") and "```" in text[3:]):
        return InputFormat.JSON_FENCE

    # 3. JSON embedded in conversational text
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = text[start : end + 1]
            try:
                json.loads(snippet)
                return InputFormat.JSON_LIKE
            except Exception:
                pass

    # 4. Markdown outline
    if re.search(r"^#{1,4}\s+", text, flags=re.MULTILINE) or re.search(r"^\s*-\s+", text, flags=re.MULTILINE):
        return InputFormat.MARKDOWN

    # 5. Plain text / Chinese outline
    return InputFormat.PLAIN_TEXT


def extract_json_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from raw text via deterministic parsing."""
    text = raw_text.strip()

    # 1. Direct JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Markdown fence extraction
    fence_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
    matches = fence_pattern.findall(text)
    for m in matches:
        cand = m.strip()
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            continue

    # 3. Outermost balanced curly braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        cand = text[start : end + 1]
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def parse_markdown_or_text_outline(raw_text: str) -> Dict[str, Any]:
    """Parse Markdown or Plain-text slide outline into structured candidate dictionary."""
    lines = [line.rstrip() for line in raw_text.strip().split("\n")]

    doc_title: Optional[str] = None
    pres_title: str = "学术论文汇报"
    venue = None
    authors: List[str] = []

    slides_data: List[Dict[str, Any]] = []
    evidence_items: List[Dict[str, Any]] = []
    current_slide: Optional[Dict[str, Any]] = None
    ev_counter = 1

    # Slide boundary pattern: '## Slide 1', '### 第2页', '第1页：背景', 'Slide 1: Intro', 'Page 1 - ...'
    slide_header_pattern = re.compile(
        r"^(?:#{1,4}\s*)?(?:第\s*(\d+)\s*[页张]|Slide\s*(\d+)|Page\s*(\d+))[\s:：\-_]*(.*)$",
        re.IGNORECASE,
    )
    # Generic markdown section pattern: '## 标题'
    general_header_pattern = re.compile(r"^#{1,3}\s+(.+)$")

    in_table = False
    table_lines: List[str] = []
    table_caption: Optional[str] = None
    table_source_ref: Optional[str] = None
    table_source_page: Optional[int] = None
    pending_table_ref: Optional[Dict[str, Any]] = None

    def _ensure_current_slide() -> Dict[str, Any]:
        nonlocal current_slide, slides_data, pres_title
        if current_slide is None:
            s_idx = len(slides_data) + 1
            current_slide = {
                "id": f"slide_{s_idx:02d}",
                "title": pres_title,
                "objective": "",
                "instructions": [],
                "bullets": [],
                "evidence_refs": [],
                "speaker_notes": None,
            }
        return current_slide

    def flush_pending_table():
        nonlocal pending_table_ref, ev_counter, current_slide
        if not pending_table_ref:
            return
        tbl_id = f"ev_tbl_{ev_counter}"
        ev_counter += 1
        evidence_items.append({
            "id": tbl_id,
            "kind": "table",
            "source_reference": pending_table_ref.get("source_reference"),
            "columns": [],
            "rows": [],
            "caption": pending_table_ref.get("caption"),
            "source_page": pending_table_ref.get("source_page"),
            "complete_table": False,
        })
        slide = _ensure_current_slide()
        slide["evidence_refs"].append(tbl_id)
        pending_table_ref = None

    def flush_table():
        nonlocal in_table, table_lines, table_caption, table_source_ref, table_source_page, ev_counter, current_slide
        if not table_lines:
            in_table = False
            return
        # Parse markdown table
        cols: List[str] = []
        rows: List[List[str]] = []
        for line in table_lines:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not cells or all(c == "" for c in cells):
                continue
            # Divider line like |---|---|
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                continue
            if not cols:
                cols = cells
            else:
                rows.append(cells)

        if cols:
            tbl_id = f"ev_tbl_{ev_counter}"
            ev_counter += 1
            tbl_ref = table_source_ref
            if not tbl_ref and table_caption:
                m = re.search(r"((?:Table|表)\s*\d+)", table_caption, re.IGNORECASE)
                if m:
                    tbl_ref = m.group(1).strip()
            tbl_ev = {
                "id": tbl_id,
                "kind": "table",
                "source_reference": tbl_ref,
                "columns": cols,
                "rows": rows,
                "caption": table_caption if table_caption else None,
                "source_page": table_source_page,
                "complete_table": all(len(r) == len(cols) for r in rows) if rows else False,
            }
            evidence_items.append(tbl_ev)
            slide = _ensure_current_slide()
            slide["evidence_refs"].append(tbl_id)

        table_lines = []
        table_caption = None
        table_source_ref = None
        table_source_page = None
        in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_table:
                flush_table()
            # If pending_table_ref is set, do NOT flush on blank lines (allows caption followed by blank line before table)
            continue

        # Check for table line
        if stripped.startswith("|") and stripped.endswith("|"):
            if pending_table_ref:
                # Next valid content is markdown table! Consume pending table metadata
                table_source_ref = pending_table_ref.get("source_reference")
                table_caption = pending_table_ref.get("caption")
                table_source_page = pending_table_ref.get("source_page")
                pending_table_ref = None
            in_table = True
            table_lines.append(stripped)
            continue
        elif in_table:
            flush_table()

        # If we have a pending table reference and the current non-empty line is NOT a table line,
        # flush it as an incomplete table placeholder before processing the current line
        if pending_table_ref:
            flush_pending_table()

        # Check title in top section
        if stripped.startswith("# ") and len(slides_data) == 0 and current_slide is None:
            pres_title = stripped.lstrip("# ").strip()
            continue

        # Check explicit paper title / source document metadata
        doc_match = re.match(r"^(?:Paper Title|论文标题|Title of Paper)[:：]\s*(.+)", stripped, re.IGNORECASE)
        if doc_match and len(slides_data) == 0 and current_slide is None:
            doc_title = doc_match.group(1).strip()
            continue

        # Check for Slide Header
        slide_match = slide_header_pattern.match(stripped)
        if slide_match:
            if in_table:
                flush_table()
            if pending_table_ref:
                flush_pending_table()
            s_num = slide_match.group(1) or slide_match.group(2) or slide_match.group(3) or str(len(slides_data) + 1)
            title = slide_match.group(4).strip() or f"Slide {s_num}"
            if current_slide:
                slides_data.append(current_slide)
            current_slide = {
                "id": f"slide_{int(s_num):02d}",
                "title": title,
                "objective": "",
                "instructions": [],
                "bullets": [],
                "evidence_refs": [],
                "speaker_notes": None,
            }
            continue

        # Check for general H2/H3 header if current slide not started or new section
        gen_match = general_header_pattern.match(stripped)
        if gen_match and not stripped.lower().startswith("## note") and not stripped.lower().startswith("## 备注"):
            title = gen_match.group(1).strip()
            if current_slide:
                slides_data.append(current_slide)
            s_idx = len(slides_data) + 1
            current_slide = {
                "id": f"slide_{s_idx:02d}",
                "title": title,
                "objective": "",
                "instructions": [],
                "bullets": [],
                "evidence_refs": [],
                "speaker_notes": None,
            }
            continue

        # Inside a slide (if current_slide is None, initialize default first slide)
        if current_slide is None:
            current_slide = {
                "id": "slide_01",
                "title": pres_title,
                "objective": "",
                "instructions": [],
                "bullets": [],
                "evidence_refs": [],
                "speaker_notes": None,
            }

        # Check for explicit presentation/layout instruction
        inst_match = re.match(r"^(?:(?:\[|\()?(?:instruction|instructions|提示|排版|布局|样式)(?:\]|\))?[:：])\s*(.*)", stripped, re.IGNORECASE)
        if inst_match:
            inst_text = inst_match.group(1).strip()
            if inst_text:
                current_slide.setdefault("instructions", []).append(inst_text)
            continue

        if current_slide:
            # Figure detection: Figure 3 / Fig. 3 / 图 3
            fig_match = re.search(r"(?:Figure|Fig\.?|图)\s*(\d+)", stripped, re.IGNORECASE)
            page_match = re.search(r"(?:Page|第)\s*(\d+)\s*(?:页|Page)?", stripped, re.IGNORECASE)
            if fig_match:
                fig_label = f"Figure {fig_match.group(1)}"
                p_num = int(page_match.group(1)) if page_match else None
                fig_id = f"ev_fig_{ev_counter}"
                ev_counter += 1
                evidence_items.append({
                    "id": fig_id,
                    "kind": "figure_reference",
                    "label": fig_label,
                    "caption": stripped,
                    "source_page": p_num,
                })
                current_slide["evidence_refs"].append(fig_id)
                continue

            # Table reference candidate: Table 2 / 表 2
            tbl_ref_match = re.search(r"((?:Table|表)\s*\d+)", stripped, re.IGNORECASE)
            if tbl_ref_match and not (stripped.startswith("|") and stripped.endswith("|")):
                tbl_raw_ref = tbl_ref_match.group(1).strip()
                p_num = int(page_match.group(1)) if page_match else None
                pending_table_ref = {
                    "source_reference": tbl_raw_ref,
                    "caption": stripped,
                    "source_page": p_num,
                }
                continue

            # Bullet / claim / metric parsing
            clean_item = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)、]\s*)", "", stripped).strip()
            if clean_item:
                # Check for explicit metric (e.g. Accuracy: 89.5% or F1 = 0.884 or 准确率达到 89.5%)
                metric_match = re.search(r"([\w\u4e00-\u9fa5\s]+)\s*(?:[:：=]|达到|约为|为)\s*([+-]?\d+(?:\.\d+)?%?(?:[a-zA-Z]+)?)", clean_item)
                if metric_match and len(metric_match.group(1).strip()) < 30:
                    m_name = metric_match.group(1).strip()
                    m_val = metric_match.group(2).strip()
                    m_id = f"ev_m_{ev_counter}"
                    ev_counter += 1
                    evidence_items.append({
                        "id": m_id,
                        "kind": "metric",
                        "name": m_name,
                        "value": m_val,
                    })
                    current_slide["evidence_refs"].append(m_id)
                else:
                    # Regular claim
                    c_id = f"ev_c_{ev_counter}"
                    ev_counter += 1
                    evidence_items.append({
                        "id": c_id,
                        "kind": "claim",
                        "content": clean_item,
                    })
                    current_slide["evidence_refs"].append(c_id)

    if in_table:
        flush_table()
    if pending_table_ref:
        flush_pending_table()

    if current_slide:
        slides_data.append(current_slide)

    # Fallback if no slides identified: create at least 1 default slide
    if not slides_data:
        slides_data.append({
            "id": "slide_01",
            "title": pres_title,
            "objective": "演示概述",
            "instructions": [],
            "bullets": [],
            "evidence_refs": [],
            "speaker_notes": None,
        })

    return {
        "spec_version": "1.0",
        "presentation": {
            "title": pres_title,
            "language": "zh-CN",
            "audience": "计算机专业研究生组会",
            "duration_minutes": 15,
            "style": "academic_clean",
            "aspect_ratio": "16:9",
        },
        "source_policy": {
            "allow_external_knowledge": False,
            "allow_inferred_facts": False,
            "allow_invented_numbers": False,
            "allow_synthetic_figures": False,
            "missing_information_policy": "omit",
        },
        "source_document": {
            "title": doc_title,
            "venue": venue,
            "authors": authors,
        },
        "evidence": evidence_items,
        "slides": slides_data,
    }


def parse_presentation_input(raw_text: str) -> Tuple[InputFormat, Dict[str, Any]]:
    """Determine format and return parsed candidate dictionary."""
    fmt = detect_format(raw_text)

    # 1. If format is JSON or JSON_FENCE or JSON_LIKE, try deterministic JSON extraction
    if fmt in (InputFormat.JSON, InputFormat.JSON_FENCE, InputFormat.JSON_LIKE):
        payload = extract_json_payload(raw_text)
        if payload is not None:
            return fmt, payload
        raise ValueError(f"Failed to extract valid JSON payload from detected {fmt.value} input.")

    # 2. Markdown or plain-text outline parsing
    candidate = parse_markdown_or_text_outline(raw_text)
    return fmt, candidate
