# Paper Understanding Layer (PR7.1)

The Paper Understanding Layer establishes the first stage of the **Research Paper Presentation Agent Pipeline**:

```text
Paper PDF
    |
    v
Paper Understanding Core (PR7.1: backend.paper)
    |
    v
PaperIR (paper_ir.json)
    |
    v
Research Presentation Planner (PR7.2)
    |
    v
Slide Semantic IR (PR7.3)
    |
    v
Layout Engine & Fidelity Exporter (PR6)
    |
    v
PPTX
```

Rather than feeding raw PDF text into an LLM to dump PowerPoint slides directly, this layer builds a clean, canonical **Paper Intermediate Representation (`PaperIR`)** with deterministic structural grounding (metadata, abstract, sections in reading order, figure and table captions, and raster image bounding boxes).

---

## 1. Architecture

```text
backend/paper/
├── __init__.py           # Stable public facade
├── schema.py             # PaperIR / PaperMetadata / PaperSection / PaperFigure / PaperTable
├── section_extractor.py  # Deterministic layout heuristics (lines, reading order, headings, captions)
├── parser.py             # Orchestrates extraction into PaperIR
└── enricher.py           # Optional LLM structured-output semantic enrichment
```

### Public API Facade

External modules should import ONLY from `backend.paper`:

```python
from backend.paper import (
    extract_paper,          # PDF path -> PaperIR
    enrich_paper,           # Optional LLM semantic enrichment (sync)
    aenrich_paper,          # Optional LLM semantic enrichment (async)
    apply_enrichment,       # Pure schema merge
    PaperIR,                # Pydantic v2 document model
    PaperMetadata,
    PaperSection,
    PaperFigure,
    PaperTable,
    BBox,
    EXTRACTOR_VERSION,
)
```

Do **not** import internals such as `section_extractor.py` directly.

---

## 2. PaperIR Data Model

A `PaperIR` represents the paper as understood before presentation planning:

```json
{
  "source_filename": "anomaly_agent.pdf",
  "metadata": {
    "title": "AnomalyAgent: Tool-Augmented Reinforcement Learning for Industrial Anomaly Synthesis",
    "authors": ["J. Researcher S. Engineer L. Supervisor"],
    "page_count": 3
  },
  "abstract": "Industrial anomaly detection is critical for manufacturing quality control...",
  "sections": [
    {
      "number": "1",
      "title": "Introduction",
      "level": 1,
      "page": 1,
      "paragraphs": ["Deep learning has driven...", "However, most pipelines..."]
    },
    {
      "number": "2",
      "title": "Related Work",
      "level": 1,
      "page": 1,
      "paragraphs": [...]
    }
  ],
  "figures": [
    {
      "id": "figure1",
      "xref_label": "Fig. 1",
      "caption": "Overview of the AnomalyAgent framework and its tool-augmented loop.",
      "page": 1,
      "is_raster": true,
      "bbox": {"x0": 144.0, "top": 460.8, "x1": 374.4, "bottom": 590.4}
    }
  ],
  "tables": [
    {
      "id": "table1",
      "xref_label": "Table 1",
      "caption": "Detection AUROC (%) comparison across benchmarks.",
      "page": 2
    }
  ],
  "contributions": [],
  "methodology": [],
  "experiments": [],
  "limitations": [],
  "extraction": {
    "engine": "pdfplumber",
    "extractor_version": "1.0.0",
    "semantic_status": "extracted"
  }
}
```

---

## 3. Deterministic Extraction Heuristics

All structural fields are extracted **without network or LLM calls**:

1. **Visual Text Lines**: Chars are clustered into visual lines by vertical coordinate proximity. Inter-word spaces are inserted when character gaps exceed `0.22 * font_size`.
2. **Reading Order & Multi-Column Support**: A vertical gutter histogram detects whether a page is single-column or two-column. Two-column pages are interleaved by topmost baseline to preserve reading order.
3. **Body Font Estimation**: The modal font size of the document (rounded to 0.25pt) serves as the baseline `body_size`.
4. **Front Matter (Title & Authors)**: On page 1, lines above the first heading with `size >= max_size - 1.2` form the title. Remaining lines before the first heading are recorded as author/affiliation lines.
5. **Heading Classification**:
   - Numbered top-level (`1. Introduction`) and subsections (`2.1 Method`) require visual emphasis (bold or `size >= body_size + 0.4`) and store clean `number` and `title`.
   - Bare known-name headings (`Abstract`, `References`) are recognized when matching canonical section sets.
6. **Captions & Image Association**:
   - Figure captions (`Fig. 1:`, `Figure 2:`) are detected and associated with the nearest raster image sitting directly above them on the same page/column.
   - Table captions (`Table 1:`, `TABLE II:`) are detected independently.
7. **Paragraph Segmentation**: Consecutive body lines are split into paragraphs when the vertical gap exceeds `2.0 * baseline_gap` or crosses a page/column boundary.

---

## 4. Optional LLM Semantic Enrichment

When a live OpenAI-compatible API key is present, `enrich_paper(paper)` calls the reasoning model to extract:
- `contributions`: Key technical contributions (bullet points)
- `methodology`: Framework highlights
- `experiments`: Main quantitative findings
- `limitations`: Stated limitations

**Reliability Guarantees**:
- Without an API key or with `mock_*` keys, the function returns immediately with `semantic_status='extracted'`.
- All outputs are strictly validated by `apply_enrichment` with sanitization (deduplication, max length, array normalization).
- Any API/JSON parsing error sets `semantic_status='enrichment_failed'` without raising.

---

## 5. Verification & Acceptance

Run the test suite:

```bash
python -m pytest tests/paper/test_parser.py -v
```

Acceptance criteria validated:
- `test_parser_title`: Paper title extracted exactly.
- `test_parser_sections_order_and_page`: All numbered sections (1..6) and unnumbered (References) in strict reading and page order.
- `test_parser_sections_clean_number_title`: Numeric prefixes stripped from title fields.
- `test_parser_figure_count_and_captions`: 3 figures detected with exact IDs and captions.
- `test_parser_figure_raster_region`: Associated raster BBoxes verified.
- `test_parser_table_count_and_captions`: 2 tables detected with captions.
- `test_extract_is_deterministic`: Byte-for-byte identical PaperIR across runs on the same PDF.
- `test_paper_ir_json_roundtrip`: Full `paper_ir.json` dump/load roundtrip fidelity.
