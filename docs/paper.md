# Paper Understanding & Presentation Planning (PR7.1 & PR7.2)

The Research Paper Presentation Agent establishes the bridge from academic papers to conference presentations:

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
Research Presentation Planner (PR7.2: backend.presentation)
    |
    v
PresentationPlan (presentation_plan.json)
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

Rather than feeding raw PDF text into an LLM to dump PowerPoint slides directly, this pipeline decouples content understanding and presentation planning from visual generation.

---

## 1. Architecture

```text
backend/
├── paper/                    # PR7.1 Paper Understanding Core
│   ├── __init__.py           # Stable public facade (extract_paper, PaperIR, etc.)
│   ├── schema.py             # PaperIR / PaperMetadata / PaperSection / PaperFigure / PaperTable
│   ├── section_extractor.py  # Deterministic layout heuristics (lines, reading order, headings, captions)
│   ├── parser.py             # Orchestrates extraction into PaperIR
│   └── enricher.py           # Optional LLM structured-output semantic enrichment
└── presentation/             # PR7.2 Research Presentation Planner
    ├── __init__.py           # Stable public facade (generate_presentation_plan, PresentationPlan, etc.)
    ├── schema.py             # SlideType, SlidePlan, PresentationPlan
    ├── ranking.py            # Section importance scoring & academic role classification
    ├── figure_selector.py    # Figure & table communicative role assignment
    ├── planner.py            # Deterministic slot synthesis & orchestration
    ├── enricher.py           # Optional LLM wording refinement (rule-first architecture)
    └── templates/
        ├── __init__.py
        └── research_default.py  # 15min (12 slides) and 10min (8 slides) profile templates
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

## 6. Research Presentation Planner (PR7.2)

The Presentation Planner answers: **"How should this paper be presented in an academic seminar?"**

### Public API Facade

External modules should import from `backend.presentation`:

```python
from backend.presentation import (
    generate_presentation_plan,   # (PaperIR, profile="research_15min", enrich=False) -> PresentationPlan
    agenerate_presentation_plan,  # Async equivalent
    PresentationPlan,             # Pydantic v2 presentation plan model
    SlidePlan,                    # Individual slide plan
    SlideType,                    # Canonical slide taxonomy enum
    rank_sections,                # Section importance ranker
    select_visuals_for_slide,     # Figure & table selector
)
```

### Presentation Profiles

- **`research_15min` (12 slides)**: Standard 15-minute lab seminar:
  1. `TITLE`: Topic, authors, and main proposition
  2. `BACKGROUND`: Problem context and practical importance
  3. `PROBLEM`: Problem formulation and bottlenecks of existing methods
  4. `MOTIVATION`: Key conceptual intuition
  5. `RELATED_WORK`: Contrasting prior art
  6. `METHOD_OVERVIEW`: End-to-end framework walk-through (bound to architecture figure)
  7. `METHOD_DETAIL`: Core mechanism & mathematical formulation
  8. `METHOD_DETAIL`: Training pipeline & optimization
  9. `EXPERIMENT_SETUP`: Benchmarks, metrics, and baselines
  10. `RESULT`: Empirical findings and comparative evaluation (bound to main table)
  11. `ABLATION`: Module breakdown and parameter sensitivity (bound to ablation table/figure)
  12. `CONCLUSION`: Summary, implications, and future directions

- **`research_10min` (8 slides)**: Spotlight presentation:
  1. `TITLE`
  2. `BACKGROUND`
  3. `METHOD_OVERVIEW`
  4. `METHOD_DETAIL`
  5. `EXPERIMENT_SETUP`
  6. `RESULT`
  7. `LIMITATION`
  8. `CONCLUSION`

### Rule-First Architecture & LLM Refinement

```text
Rule-First Deterministic Planner
       |
       v
Candidate PresentationPlan (exact slide count, types, figure bindings, initial points)
       |
       v (optional, enrich=True)
LLM Refinement (enricher.py)
       |
       v
Refined PresentationPlan (crisp academic wording, structure 100% preserved)
```

- **Guaranteed Structure**: The slide count, `slide_type`, index, `source_sections`, `source_figures`, and `source_tables` are computed deterministically.
- **Zero-Network Degradation**: If no live key is set or the LLM call fails, the deterministic candidate plan is returned immediately.


---

## 7. Slide Semantic IR (PR9)

The Slide Semantic IR Layer (`backend/slidespec`) defines the structured semantic layout contract between high-level presentation planning and visual layout rendering.

### Decoupling Principle

- **Does NOT assign pixel coordinates** (`left`, `top`, `width`, `height`).
- Establishes **Macro Visual Intents** (`TITLE_HERO`, `PIPELINE_ARCHITECTURE`, `BENCHMARK_COMPARISON`, `TWO_COLUMN_CONTRAST`, `KEY_TAKEAWAY_LIST`).
- Establishes **Micro Semantic Roles** (`HEADING`, `SUBHEADING`, `LEAD_SUMMARY`, `BULLET_ITEM`, `CAPTION`, `BADGE`).
- Encapsulates figure and table blocks referencing PaperIR assets.

### Public API Facade

```python
from backend.slidespec import (
    SlideSpec,                          # Semantic IR for an individual slide
    DeckSpec,                           # Full deck specification
    VisualIntent,                       # Visual layout intent enum
    BlockRole,                          # Textual block role enum
    ContentBlock,                       # Polymorphic block union
    TextBlock, FigureBlock, TableBlock, BadgeBlock,
    map_presentation_plan_to_deck_spec, # Canonical mapper
)
```

---

## 8. Layout Engine & Academic Geometry Synthesis (PR10)

`LayoutEngine` maps semantic `SlideSpec` specifications into deterministic `LayoutSpec` geometry without calling downstream presentation libraries like `python-pptx`.

```
SlideSpec (Semantic visual intent, no coords)
  -> Layout Engine / Synthesis (PR10: computes geometry & constraints)
  -> LayoutSpec (Deterministic coordinates, typography, safe zones)
  -> PPTX Renderer (PR11: shapes, tables, pictures, theme)
```

### Key Principles & Features
- **Normalized 16:9 Canvas**: 1280×720 ViewBox standard with explicit safe margins (`MARGIN_LEFT=64`, `MARGIN_RIGHT=64`, `MARGIN_TOP=40`, `MARGIN_BOTTOM=40`).
- **Layout Templates**:
  - `TITLE_HERO`: Centered academic hero with title, author subtitle, and venue badges.
  - `PIPELINE_ARCHITECTURE`: Split stage explanations (left) + visual diagram container (right).
  - `BENCHMARK_COMPARISON`: Empirical evidence asset (table/figure, 60% width) + key takeaway cards (40% width).
  - `TWO_COLUMN_CONTRAST`: Balanced side-by-side columns (e.g. baseline vs ours, problem vs solution).
  - `KEY_TAKEAWAY_LIST`: Vertically stacked summary cards.
  - `METRIC_CARD_GRID`: 1x3 or 2x2 multi-metric grid layouts.
- **Formal Geometric Constraints (`constraints.py`)**: Canvas bounds enforcement, pairwise non-overlap validation, figure aspect ratio preservation, and text overflow estimation.
- **Strict Quality Validator (`validator.py`)**: Prevents out-of-bounds positioning, collision overlaps, empty text, or missing asset links.
- **100% Deterministic Synthesis**: 100 consecutive runs yield byte-for-byte identical coordinate hashes.

### Public Layout API Facade

```python
from backend.layout import (
    Canvas,
    Rect,
    ElementType,
    TextStyle,
    ElementStyle,
    LayoutElement,
    LayoutConstraint,
    LayoutSpec,
    DeckLayoutSpec,
    generate_layout,
    generate_deck_layout,
    validate_layout,
)
```

---

## 9. Verification & Acceptance

```bash
python -m pytest tests/paper tests/presentation tests/slidespec tests/layout -v
```

Acceptance criteria validated:
- `tests/paper`: Structural completeness, figure/table captions, and deterministic PDF extraction (16 tests).
- `tests/presentation`: Academic template profile slots, section ranking, and structural guards (29 tests).
- `tests/slidespec`: Semantic IR polymorphism, visual intent mapping, and JSON roundtrip fidelity (18 tests).
- `tests/layout`: Geometric primitives, collision avoidance, 100-run determinism, template synthesis, constraint validation, and end-to-end PDF -> LayoutSpec pipeline (23 tests).
- **Total Suite Passing**: 86 passing tests with zero regressions.
