# PPT-Agent-Studio Architecture Status & Roadmap

This document defines the current baseline state, active developments, and future roadmap for the PPT-Agent-Studio project.

---

## 1. Completed

### Core PPT-IR Representation & State
- **1280×720 ViewBox Standard**: Decoupled presentation state from binary file formats.
- **Strong Typing**: Pydantic / dataclass definitions covering slides, shapes, text runs, connectors, images, and visual styles.
- **Reversible Patch Engine (`HistoryManager`)**: Fine-grained JSON-patch style state tracking with bidirectional Undo/Redo capabilities.

### Agent Runtime & State Machine
- **LangGraph StateGraph Workflow**: Explicit state machine managing routing, planning, tool execution, visual critique, and user summaries.
- **Tool Suite**: Slide generation archetypes (card grid, timeline, KPI metrics, comparison), batch card creation, intelligent alignment, element manipulation, and typography formatting.
- **Multi-Role LLM Dispatch**: Support for general reasoning, vision critique, and fast parameter formatting.

### Interactive Canvas & Studio Frontend
- **Direct Canvas Manipulation**: Smooth element dragging and 8-direction precision resize handles with coordinate boundary constraints.
- **HTML5 Drag-and-Drop**: Placement of text, cards, shapes, and connectors from the top toolbar onto canvas coordinates.
- **Figma-Style Property Inspector**: Font family selection, font size steppers and presets, bold/italic, alignments, layout presets, and corner radius.
- **Real-Time WebSocket Sync**: Sub-second synchronization between user canvas actions, agent modifications, and multi-client broadcast.

### Package Validation & Regression Gates
- **OOXML Validator (`validate_pptx`)**: Inspects archive health, `presentation.xml`, slide collections, and relationships.
- **Multi-Fixture Smoke Test Gate (`test_roundtrip_smoke.py`)**: Validates the closed-loop pipeline (`PPTX -> OOXML Extractor -> PPT-IR -> OOXML Renderer -> PPTX`) across diverse presentation archetypes (`simple.pptx`, `academic.pptx`, `diagram.pptx`, `image-heavy.pptx`).
- **Conversion Fidelity Reporting (`ConversionReport`)**: Transparent tracking of converted vs. skipped elements with unified counting in `element_to_ir` to eliminate group double-counting, alongside explicit warning logs.

### Fidelity Engine Hardening (PR6.1)
- **Capability Matrix**: `FidelityCapability` and `CapabilityDetector` distinguishing editable features from detect-only boundaries (chart / smartart / animation / master).
- **Partial-Failure Tolerant Import**: Corrupt parts emit warnings rather than hard-crashing.
- **Risk-Gated Mutation Policy**: `ActionRiskPolicy` ensuring proportional confidence thresholds (delete 0.95, move/resize 0.85, style 0.75).
- **Regression Guard & Rollback**: `FidelityRegressionGuard` protecting sub-metric fidelity limits (geometry <= 5 pts, text/style/visual <= 10 pts, critical floor 85).
- **Structured Fidelity Reporting**: `FidelityReport` surfacing actionable remediation issues for the agent.

### Research Paper Understanding Core (PR7.1)
- **Paper Intermediate Representation (`PaperIR`)**: Strongly-typed Pydantic v2 document model (`metadata`, `abstract`, `sections`, `figures`, `tables`, `contributions`, `methodology`, `experiments`, `limitations`).
- **Deterministic PDF Structural Extractor**: Zero-network heuristics extracting paper title, author bylines, reading order, numbered section hierarchy, figure/table captions, and raster image bounding boxes.
- **Optional LLM Semantic Enrichment**: Fault-tolerant reasoning layer to extract research contributions and limitations when a live API key is configured.
- **Deterministic Academic PDF Fixture**: Self-contained `tests/fixtures/paper/anomaly_agent.pdf` with automated generator `scripts/create_paper_fixtures.py`.
- **Full Acceptance Suite**: 16 dedicated unit and acceptance tests validating structural completeness and JSON round-trip stability.

### Research Presentation Planner (PR7.2)
- **Presentation Plan Representation (`PresentationPlan`)**: Strongly-typed Pydantic v2 presentation plan (`SlideType`, `SlidePlan`, `PresentationPlan`) with lossless JSON round-trip serialization.
- **Standard Academic Profiles**: Deterministic slot-based templates for `research_15min` (12 slides: Title, Background, Problem, Motivation, Related Work, Method Overview, Method Details, Algorithm, Setup, Results, Ablation, Conclusion) and `research_10min` (8 slides).
- **Section Importance Ranking (`ranking.py`)**: Normalized academic relevance scoring and semantic role classification prioritizing Method and Experiment sections while filtering References and Appendix.
- **Figure & Table Selection (`figure_selector.py`)**: Smart visual evidence binding mapping architecture diagrams to `METHOD_OVERVIEW`, comparative benchmark tables to `RESULT`, and ablation tables to `ABLATION`.
- **Rule-First Architecture with Optional LLM Refinement (`enricher.py`)**: Guarantees deterministic structure and bullet points with non-destructive LLM wording refinement and safe zero-network degradation.
- **Comprehensive Test Suite**: 13 unit and acceptance tests covering schema roundtrip, ranking, figure selection, profile slots, and deterministic plan generation.

### Slide Semantic IR & Academic Layout Contract (PR9)
- **SlideSpec & DeckSpec Models**: Strongly-typed semantic intermediate representation (`SlideSpec`, `DeckSpec`) decoupling communicative intent from pixel geometry.
- **Visual Intent Archetypes (`VisualIntent`)**: `TITLE_HERO`, `PIPELINE_ARCHITECTURE`, `BENCHMARK_COMPARISON`, `TWO_COLUMN_CONTRAST`, `METRIC_CARD_GRID`, `KEY_TAKEAWAY_LIST`.
- **Polymorphic Content Blocks (`ContentBlock`)**: `TextBlock` (with `BlockRole` hierarchy: heading, subheading, lead summary, bullet item, caption, badge, callout), `FigureBlock`, `TableBlock`, and `BadgeBlock`.
- **Deterministic Semantic Mapper (`mapper.py`)**: Transforms `PresentationPlan` + `PaperIR` into fully grounded `DeckSpec` with asset linkage and provenance.
- **Complete Test Suite (`tests/slidespec/`)**: Tests covering polymorphic block serialization, deck roundtrip, intent mapping, and end-to-end PDF -> PaperIR -> PresentationPlan -> DeckSpec -> JSON pipeline.

### Layout Engine & Academic Geometry Synthesis (PR10)
- **Geometry & Layout Intermediate Representation (`LayoutSpec`, `DeckLayoutSpec`)**: Strongly-typed geometric representation with normalized 1280×720 ViewBox coordinates, explicit bounding rectangles (`Rect`), typography styles (`TextStyle`), and safe boundary zones.
- **Template Synthesis & Spatial Solvers (`backend/layout/templates/`)**: Dedicated academic templates for `TITLE_HERO`, `PIPELINE_ARCHITECTURE`, `BENCHMARK_COMPARISON`, `TWO_COLUMN_CONTRAST`, `KEY_TAKEAWAY_LIST`, and `METRIC_CARD_GRID`.
- **Formal Geometric Constraints System (`constraints.py`)**: Canvas bounds enforcement, pairwise non-overlap verification, figure aspect ratio integrity protection, and text overflow estimation.
- **Strict Quality Validator (`validator.py`)**: Detects out-of-bounds coordinates, collision artifacts, empty content, and missing asset references with strict/warning report modes.
- **100% Deterministic Execution**: Validated across 100 consecutive synthesis runs producing zero layout drift or coordinate discrepancies.
- **Comprehensive Test Suite (`tests/layout/`)**: 23 unit and acceptance tests covering schema roundtrip, template synthesis, constraint validation, determinism, and full end-to-end PDF -> PaperIR -> PresentationPlan -> DeckSpec -> DeckLayoutSpec -> JSON pipeline.

### PPTX Fidelity Renderer & OOXML Export Layer (PR11)
- **Zero-Loss OOXML Translation (`backend/renderer/renderer.py`)**: Directly maps `DeckLayoutSpec` (1280×720 ViewBox) into native PowerPoint (`.pptx`) presentations via strict $1\text{ px} = 9525\text{ EMUs}$ translation without recomputing layout.
- **Strict Architectural Boundaries**: `render_pptx` enforces `DeckLayoutSpec` input exclusivity, preventing direct invocation from `SlideSpec` or raw planning objects.
- **Encapsulated Builder (`pptx_builder.py`)**: Isolates `python-pptx` behind a clean presentation builder facade (`add_text`, `add_image`, `add_table`, `add_shape`, `save`).
- **Academic Theme System (`theme.py` & `typography.py`)**: Academic typography hierarchy, color palettes, and spacing rules ensuring no hardcoded magic font sizes appear in renderer code.
- **Asset Resolver & Diagram Synthesis (`assets.py`)**: Maps `source_figure_id` and `source_table_id` to raster disk assets or synthesizes elegant academic placeholder figures and structured tables.
- **Fidelity Validator & Visual Exporter (`validators.py`)**: Automated verification of slide count, shape types, text containment, and geometry fidelity with coordinate error $< 1.0\%$ (empirically $0.0\%$), plus automated slide screenshot export via PowerPoint COM.
- **Comprehensive Acceptance Test Suite (`tests/renderer/`)**: 20 dedicated unit and pipeline acceptance tests covering text, figures, tables, themes, and full end-to-end PDF -> PaperIR -> PresentationPlan -> SlideSpec -> LayoutSpec -> PPTX export.

---

## 2. In Progress

### Visual Evaluation & Agent Editing (PR12 & PR13)
- **PR12 Visual Evaluation Loop**: Multi-modal vision critique of rendered slide screenshots with automated layout self-healing.
- **PR13 Agent Editing Interface**: Conversational and iterative presentation editing actions.

---

## 3. Future

- **Vision Auto-Correction**:
  - Full automated closed-loop where multi-modal vision models inspect rendered slide screenshots and self-correct layout overlaps or contrast flaws.
- **Multi-Agent Designer Swarm**:
  - Specialized agent teams (e.g., Content Researcher, Typographer, Graphic Designer, Layout Critic) collaborating asynchronously on full presentation decks.
- **Extended OOXML Capabilities**:
  - Editable support for charts, SmartArt, and master-slide inheritance (currently detect-only; charts/SmartArt noted as known coverage boundaries in the real-world benchmark).
